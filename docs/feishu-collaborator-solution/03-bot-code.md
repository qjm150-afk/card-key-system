# 飞书机器人代码实现

## 项目结构

```
feishu-card-key-bot/
├── src/
│   ├── index.js              # 入口文件
│   ├── handlers/
│   │   └── permission.js     # 权限申请处理
│   ├── services/
│   │   ├── bitable.js        # 多维表格服务
│   │   ├── permission.js     # 权限服务
│   │   └── message.js        # 消息服务
│   ├── utils/
│   │   ├── cardKey.js        # 卡密解析工具
│   │   └── date.js           # 日期处理工具
│   └── config/
│       └── index.js          # 配置文件
├── package.json
└── README.md
```

---

## 核心代码实现

### 1. 配置文件 (src/config/index.js)

```javascript
/**
 * 飞书机器人配置
 */
module.exports = {
  // 飞书应用配置
  app: {
    appId: process.env.FEISHU_APP_ID,
    appSecret: process.env.FEISHU_APP_SECRET,
  },
  
  // 多维表格配置
  bitable: {
    appToken: process.env.BITABLE_APP_TOKEN,  // 多维表格的 app_token
    tables: {
      cardKeys: 'card_keys',      // 卡密表名
      logs: 'access_logs',        // 日志表名
    }
  },
  
  // 权限配置
  permission: {
    defaultPerm: 'view',  // 默认权限：view, edit, full_access
  },
  
  // 卡密格式配置
  cardKey: {
    patterns: [
      /【卡密】([A-Z0-9-]+)/i,           // 【卡密】ABC-1234-5678-XYZ
      /卡密[：:]\s*([A-Z0-9-]+)/i,       // 卡密：ABC-1234-5678-XYZ
      /([A-Z]{2,4}-\d{4}-\d{4}-[A-Z0-9]+)/i  // ABC-1234-5678-XYZ
    ]
  }
};
```

---

### 2. 入口文件 (src/index.js)

```javascript
const lark = require('@larksuiteoapi/node-sdk');
const config = require('./config');
const { handlePermissionApply } = require('./handlers/permission');

// 初始化飞书客户端
const client = new lark.Client({
  appId: config.app.appId,
  appSecret: config.app.appSecret,
  appType: lark.AppType.SelfBuild,
  domain: lark.Domain.Feishu
});

// 飞书云函数入口
exports.handler = async (event, context) => {
  try {
    const body = JSON.parse(event.body);
    
    // 处理 URL 验证
    if (body.type === 'url_verification') {
      return {
        statusCode: 200,
        body: JSON.stringify({ challenge: body.challenge })
      };
    }
    
    // 处理权限申请事件
    if (body.header?.event_type === 'drive.permission.apply_event_v1') {
      await handlePermissionApply(client, body.event);
    }
    
    return {
      statusCode: 200,
      body: JSON.stringify({ code: 0, msg: 'success' })
    };
  } catch (error) {
    console.error('处理请求失败:', error);
    return {
      statusCode: 500,
      body: JSON.stringify({ code: -1, msg: error.message })
    };
  }
};

// 本地开发入口
if (require.main === module) {
  const express = require('express');
  const app = express();
  app.use(express.json());
  
  app.post('/webhook', async (req, res) => {
    try {
      const body = req.body;
      
      // URL 验证
      if (body.type === 'url_verification') {
        return res.json({ challenge: body.challenge });
      }
      
      // 处理事件
      if (body.header?.event_type === 'drive.permission.apply_event_v1') {
        await handlePermissionApply(client, body.event);
      }
      
      res.json({ code: 0, msg: 'success' });
    } catch (error) {
      console.error('处理请求失败:', error);
      res.status(500).json({ code: -1, msg: error.message });
    }
  });
  
  const PORT = process.env.PORT || 3000;
  app.listen(PORT, () => {
    console.log(`服务器启动: http://localhost:${PORT}`);
  });
}
```

---

### 3. 权限申请处理器 (src/handlers/permission.js)

```javascript
const config = require('../config');
const { extractCardKey } = require('../utils/cardKey');
const { queryCardKey, updateCardKey, createLog } = require('../services/bitable');
const { addCollaborator } = require('../services/permission');
const { sendTextMessage } = require('../services/message');
const { isCardExpired } = require('../utils/date');

/**
 * 处理权限申请事件
 */
async function handlePermissionApply(client, event) {
  const { file_token, applicant_user_id, apply_reason, file_type, token_type } = event;
  
  console.log(`[权限申请] 用户: ${applicant_user_id}, 文件: ${file_token}, 理由: ${apply_reason}`);
  
  // 1. 从申请理由中提取卡密
  const cardKey = extractCardKey(apply_reason);
  
  if (!cardKey) {
    console.log(`[权限申请] 未找到有效卡密`);
    await rejectAndNotify(client, {
      fileToken: file_token,
      userId: applicant_user_id,
      reason: '未提供有效卡密，请在申请理由中填写卡密。\n格式：【卡密】ABC-1234-5678-XYZ'
    });
    return;
  }
  
  console.log(`[权限申请] 提取到卡密: ${cardKey}`);
  
  // 2. 查询卡密
  const card = await queryCardKey(client, cardKey);
  
  if (!card) {
    console.log(`[权限申请] 卡密不存在: ${cardKey}`);
    await rejectAndNotify(client, {
      fileToken: file_token,
      userId: applicant_user_id,
      reason: '卡密不存在，请检查后重试'
    });
    return;
  }
  
  // 3. 检查卡密状态
  if (card.状态 !== '有效') {
    console.log(`[权限申请] 卡密状态无效: ${card.状态}`);
    await rejectAndNotify(client, {
      fileToken: file_token,
      userId: applicant_user_id,
      reason: `卡密已${card.状态}，无法使用`
    });
    return;
  }
  
  // 4. 检查是否过期
  const expired = isCardExpired(card);
  if (expired) {
    console.log(`[权限申请] 卡密已过期`);
    await rejectAndNotify(client, {
      fileToken: file_token,
      userId: applicant_user_id,
      reason: '卡密已过期'
    });
    return;
  }
  
  // 5. 检查是否已被其他用户使用（一卡一用户）
  if (card.绑定用户 && card.绑定用户 !== applicant_user_id) {
    console.log(`[权限申请] 卡密已被其他用户使用`);
    await rejectAndNotify(client, {
      fileToken: file_token,
      userId: applicant_user_id,
      reason: '卡密已被其他用户使用'
    });
    return;
  }
  
  // 6. 检查使用次数限制
  if (card.最大使用次数 && card.使用次数 >= card.最大使用次数) {
    console.log(`[权限申请] 卡密使用次数已达上限`);
    await rejectAndNotify(client, {
      fileToken: file_token,
      userId: applicant_user_id,
      reason: `卡密使用次数已达上限（${card.最大使用次数}次）`
    });
    return;
  }
  
  // 7. 添加用户为协作者
  try {
    await addCollaborator(client, {
      fileToken: file_token,
      fileType: token_type || file_type,
      userId: applicant_user_id,
      perm: config.permission.defaultPerm
    });
    console.log(`[权限申请] 添加协作者成功`);
  } catch (error) {
    console.error(`[权限申请] 添加协作者失败:`, error);
    await rejectAndNotify(client, {
      fileToken: file_token,
      userId: applicant_user_id,
      reason: '系统错误，请稍后重试'
    });
    return;
  }
  
  // 8. 更新卡密状态
  await updateCardKey(client, card.id, {
    激活时间: card.激活时间 || new Date().toISOString(),
    绑定用户: applicant_user_id,
    使用次数: (card.使用次数 || 0) + 1
  });
  console.log(`[权限申请] 更新卡密状态成功`);
  
  // 9. 记录日志
  await createLog(client, {
    卡密: card.id,
    申请用户: applicant_user_id,
    申请理由: apply_reason,
    验证结果: '通过',
    文档Token: file_token
  });
  console.log(`[权限申请] 记录日志成功`);
  
  // 10. 通知用户
  await sendTextMessage(client, applicant_user_id, 
    `✅ 卡密验证成功！\n\n` +
    `您已获得访问权限，可以查看文档内容。\n\n` +
    `有效期：${getExpireInfo(card)}`
  );
  console.log(`[权限申请] 通知用户成功`);
}

/**
 * 拒绝申请并通知用户
 */
async function rejectAndNotify(client, { fileToken, userId, reason }) {
  // 记录失败日志
  await createLog(client, {
    申请用户: userId,
    申请理由: reason,
    验证结果: '拒绝',
    拒绝原因: reason,
    文档Token: fileToken
  });
  
  // 发送消息通知用户
  await sendTextMessage(client, userId, `❌ 权限申请被拒绝\n\n原因：${reason}`);
}

/**
 * 获取过期信息描述
 */
function getExpireInfo(card) {
  switch (card.过期类型) {
    case '永久':
      return '永久有效';
    case '固定日期':
      return `有效期至 ${card.过期时间}`;
    case '激活后N天':
      return `激活后 ${card.有效天数} 天有效`;
    default:
      return '未知';
  }
}

module.exports = { handlePermissionApply };
```

---

### 4. 多维表格服务 (src/services/bitable.js)

```javascript
const config = require('../config');

/**
 * 查询卡密
 */
async function queryCardKey(client, cardKey) {
  const response = await client.bitable.appTableRecord.list({
    path: {
      app_token: config.bitable.appToken,
      table_id: config.bitable.tables.cardKeys,
    },
    params: {
      filter: `CurrentValue.[卡密] = "${cardKey}"`,
    },
  });
  
  if (response.data?.items?.length > 0) {
    const record = response.data.items[0];
    return {
      id: record.record_id,
      ...record.fields
    };
  }
  
  return null;
}

/**
 * 更新卡密
 */
async function updateCardKey(client, recordId, fields) {
  const response = await client.bitable.appTableRecord.update({
    path: {
      app_token: config.bitable.appToken,
      table_id: config.bitable.tables.cardKeys,
      record_id: recordId,
    },
    params: {
      user_id_type: 'user_id',
    },
    data: {
      fields: fields
    },
  });
  
  return response.data;
}

/**
 * 创建验证日志
 */
async function createLog(client, data) {
  const fields = {
    申请用户: data.申请用户 ? { id: data.申请用户 } : null,
    申请理由: data.申请理由 || '',
    验证结果: data.验证结果 || '',
    拒绝原因: data.拒绝原因 || '',
    文档Token: data.文档Token || '',
  };
  
  // 如果有关联的卡密，添加关联
  if (data.卡密) {
    fields.卡密 = [{ id: data.卡密 }];
  }
  
  const response = await client.bitable.appTableRecord.create({
    path: {
      app_token: config.bitable.appToken,
      table_id: config.bitable.tables.logs,
    },
    params: {
      user_id_type: 'user_id',
    },
    data: {
      fields: fields
    },
  });
  
  return response.data;
}

/**
 * 批量创建卡密
 */
async function batchCreateCardKeys(client, cardKeys) {
  const records = cardKeys.map(card => ({
    fields: {
      卡密: card.卡密,
      状态: card.状态 || '有效',
      文档链接: card.文档链接,
      过期类型: card.过期类型 || '永久',
      过期时间: card.过期时间 || null,
      有效天数: card.有效天数 || null,
      销售状态: card.销售状态 || '未售出',
      使用次数: 0,
    }
  }));
  
  const response = await client.bitable.appTableRecord.batchCreate({
    path: {
      app_token: config.bitable.appToken,
      table_id: config.bitable.tables.cardKeys,
    },
    data: {
      records: records
    },
  });
  
  return response.data;
}

module.exports = {
  queryCardKey,
  updateCardKey,
  createLog,
  batchCreateCardKeys
};
```

---

### 5. 权限服务 (src/services/permission.js)

```javascript
/**
 * 添加协作者
 */
async function addCollaborator(client, { fileToken, fileType, userId, perm }) {
  const response = await client.drive.permissionMember.create({
    path: {
      token: fileToken,
      type: fileType || 'file',
    },
    params: {
      need_notification: true,
    },
    data: {
      member_type: 'userid',
      member_id: userId,
      perm: perm || 'view', // view, edit, full_access
    },
  });
  
  return response.data;
}

/**
 * 移除协作者
 */
async function removeCollaborator(client, { fileToken, fileType, memberId }) {
  const response = await client.drive.permissionMember.delete({
    path: {
      token: fileToken,
      type: fileType || 'file',
    },
    data: {
      member_type: 'userid',
      member_id: memberId,
    },
  });
  
  return response.data;
}

/**
 * 查询协作者列表
 */
async function listCollaborators(client, { fileToken, fileType }) {
  const response = await client.drive.permissionMember.list({
    path: {
      token: fileToken,
      type: fileType || 'file',
    },
  });
  
  return response.data;
}

module.exports = {
  addCollaborator,
  removeCollaborator,
  listCollaborators
};
```

---

### 6. 消息服务 (src/services/message.js)

```javascript
/**
 * 发送文本消息
 */
async function sendTextMessage(client, userId, text) {
  const response = await client.im.message.create({
    params: {
      receive_id_type: 'user_id',
    },
    data: {
      receive_id: userId,
      msg_type: 'text',
      content: JSON.stringify({ text: text }),
    },
  });
  
  return response.data;
}

/**
 * 发送卡片消息
 */
async function sendCardMessage(client, userId, card) {
  const response = await client.im.message.create({
    params: {
      receive_id_type: 'user_id',
    },
    data: {
      receive_id: userId,
      msg_type: 'interactive',
      content: JSON.stringify(card),
    },
  });
  
  return response.data;
}

module.exports = {
  sendTextMessage,
  sendCardMessage
};
```

---

### 7. 卡密解析工具 (src/utils/cardKey.js)

```javascript
const config = require('../config');

/**
 * 从文本中提取卡密
 * @param {string} text - 申请理由文本
 * @returns {string|null} - 卡密或null
 */
function extractCardKey(text) {
  if (!text) return null;
  
  const patterns = config.cardKey.patterns;
  
  for (const pattern of patterns) {
    const match = text.match(pattern);
    if (match && match[1]) {
      return match[1].toUpperCase();
    }
  }
  
  return null;
}

/**
 * 生成卡密
 * @param {string} prefix - 前缀，如 'ABC'
 * @returns {string} - 卡密
 */
function generateCardKey(prefix = 'ABC') {
  const chars = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ';
  const segments = [];
  
  for (let i = 0; i < 3; i++) {
    let segment = '';
    for (let j = 0; j < 4; j++) {
      segment += chars.charAt(Math.floor(Math.random() * chars.length));
    }
    segments.push(segment);
  }
  
  return `${prefix}-${segments.join('-')}`;
}

/**
 * 批量生成卡密
 * @param {number} count - 数量
 * @param {string} prefix - 前缀
 * @returns {string[]} - 卡密数组
 */
function generateCardKeys(count, prefix = 'ABC') {
  const keys = new Set();
  while (keys.size < count) {
    keys.add(generateCardKey(prefix));
  }
  return Array.from(keys);
}

module.exports = {
  extractCardKey,
  generateCardKey,
  generateCardKeys
};
```

---

### 8. 日期处理工具 (src/utils/date.js)

```javascript
/**
 * 判断卡密是否过期
 * @param {object} card - 卡密记录
 * @returns {boolean} - 是否过期
 */
function isCardExpired(card) {
  const now = new Date();
  
  switch (card.过期类型) {
    case '永久':
      return false;
      
    case '固定日期':
      if (!card.过期时间) return false;
      const expireDate = new Date(card.过期时间);
      return now > expireDate;
      
    case '激活后N天':
      if (!card.激活时间 || !card.有效天数) return false;
      const activatedDate = new Date(card.激活时间);
      const expireAfterDays = new Date(activatedDate);
      expireAfterDays.setDate(expireAfterDays.getDate() + card.有效天数);
      return now > expireAfterDays;
      
    default:
      return false;
  }
}

/**
 * 计算过期时间
 * @param {object} card - 卡密记录
 * @returns {Date|null} - 过期时间
 */
function calculateExpireDate(card) {
  switch (card.过期类型) {
    case '永久':
      return null;
      
    case '固定日期':
      return card.过期时间 ? new Date(card.过期时间) : null;
      
    case '激活后N天':
      if (!card.激活时间 || !card.有效天数) return null;
      const activatedDate = new Date(card.激活时间);
      activatedDate.setDate(activatedDate.getDate() + card.有效天数);
      return activatedDate;
      
    default:
      return null;
  }
}

/**
 * 格式化日期
 * @param {Date|string} date - 日期
 * @returns {string} - 格式化后的日期
 */
function formatDate(date) {
  if (!date) return '-';
  const d = new Date(date);
  return d.toLocaleDateString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit'
  });
}

module.exports = {
  isCardExpired,
  calculateExpireDate,
  formatDate
};
```

---

## package.json

```json
{
  "name": "feishu-card-key-bot",
  "version": "1.0.0",
  "description": "飞书卡密验证机器人 - 自动审批文档权限",
  "main": "src/index.js",
  "scripts": {
    "start": "node src/index.js",
    "dev": "nodemon src/index.js"
  },
  "dependencies": {
    "@larksuiteoapi/node-sdk": "^1.25.0",
    "express": "^4.18.2"
  },
  "devDependencies": {
    "nodemon": "^3.0.1"
  }
}
```

---

## 环境变量

```bash
# 飞书应用配置
FEISHU_APP_ID=cli_xxxxxxxxxxxx
FEISHU_APP_SECRET=xxxxxxxxxxxxxxxxxx

# 多维表格配置
BITABLE_APP_TOKEN=xxxxxxxxxxxxxxxxxx
```
