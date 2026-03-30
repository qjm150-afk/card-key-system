import { S3Storage } from "coze-coding-dev-sdk";
import { readFileSync } from "fs";
import { fileURLToPath } from "url";
import { dirname, join } from "path";

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

const storage = new S3Storage({
  endpointUrl: process.env.COZE_BUCKET_ENDPOINT_URL,
  accessKey: "",
  secretKey: "",
  bucketName: process.env.COZE_BUCKET_NAME,
  region: "cn-beijing",
});

async function main() {
  // 上传管理后台测试版
  const adminHtml = readFileSync("/workspace/projects/src/static/admin-test.html");
  const adminKey = await storage.uploadFile({
    fileContent: adminHtml,
    fileName: "test/admin-test.html",
    contentType: "text/html",
  });
  console.log("管理后台测试版已上传，key:", adminKey);

  // 上传前端测试版
  const indexHtml = readFileSync("/workspace/projects/src/static/index-test.html");
  const indexKey = await storage.uploadFile({
    fileContent: indexHtml,
    fileName: "test/index-test.html",
    contentType: "text/html",
  });
  console.log("前端测试版已上传，key:", indexKey);

  // 生成签名 URL（有效期 7 天）
  const adminUrl = await storage.generatePresignedUrl({
    key: adminKey,
    expireTime: 604800, // 7 天
  });
  const indexUrl = await storage.generatePresignedUrl({
    key: indexKey,
    expireTime: 604800, // 7 天
  });

  console.log("\n========================================");
  console.log("📥 测试文件下载链接（有效期 7 天）：");
  console.log("========================================");
  console.log("\n🔧 管理后台测试版：");
  console.log(adminUrl);
  console.log("\n🔑 前端验证页面测试版：");
  console.log(indexUrl);
  console.log("\n========================================");
  console.log("使用说明：");
  console.log("1. 点击链接下载 HTML 文件");
  console.log("2. 直接在浏览器中打开下载的文件");
  console.log("3. 管理后台密码: qjmadmin2024");
  console.log("========================================");
}

main().catch(console.error);
