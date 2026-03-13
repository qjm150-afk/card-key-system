"""
数据库客户端 - 支持双模式切换
- 云端部署：使用 Coze Supabase
- 本地开发：使用 SQLite

环境变量说明：
- LOCAL_DEV_MODE=true: 强制使用本地 SQLite 数据库（本地开发/测试）
- COZE_SUPABASE_URL: 云端 Supabase 地址（生产环境）

判断逻辑：
1. 如果 LOCAL_DEV_MODE=true，强制使用 SQLite（优先级最高）
2. 如果 COZE_SUPABASE_URL 存在且 LOCAL_DEV_MODE 未设置，使用 Supabase
3. 否则默认使用 SQLite
"""

import os
from typing import Optional, Any, Dict, List
from datetime import datetime
import json
import sqlite3
from contextlib import contextmanager

# ============================================
# 环境判断
# ============================================

def is_local_dev_mode() -> bool:
    """判断是否为本地开发模式"""
    local_dev = os.getenv("LOCAL_DEV_MODE", "").lower()
    return local_dev in ("true", "1", "yes")


def is_production() -> bool:
    """判断是否为生产环境（云端部署）
    
    优先级：
    1. LOCAL_DEV_MODE=true → 返回 False（强制本地模式）
    2. COZE_SUPABASE_URL 存在 → 返回 True（生产环境）
    3. 默认 → 返回 False（本地模式）
    """
    # 本地开发模式优先级最高
    if is_local_dev_mode():
        return False
    
    # 有 Supabase URL 且未设置本地模式，则为生产环境
    return bool(os.getenv("COZE_SUPABASE_URL"))


def get_db_mode() -> str:
    """获取当前数据库模式名称"""
    return "sqlite (local)" if not is_production() else "supabase (production)"


# ============================================
# SQLite 客户端（本地开发）
# ============================================

# 本地数据库默认路径
SQLITE_DB_PATH = os.getenv("LOCAL_DB_PATH", "/tmp/card_key_local.db")


class SQLiteResponse:
    """SQLite 响应 - 模拟 Supabase Response"""
    
    def __init__(self, data: List[Dict], count: int = None):
        self.data = data
        self.count = count


class SQLiteClient:
    """SQLite 数据库客户端 - 模拟 Supabase 接口"""
    
    def __init__(self, db_path: str = SQLITE_DB_PATH):
        self.db_path = db_path
        self._init_tables()
    
    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn
    
    def _init_tables(self):
        """初始化表结构"""
        with self._get_connection() as conn:
            # 卡密表
            conn.execute("""
                CREATE TABLE IF NOT EXISTS card_keys_table (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    key_value TEXT UNIQUE NOT NULL,
                    status INTEGER DEFAULT 1,
                    feishu_url TEXT,
                    feishu_password TEXT,
                    link_name TEXT,
                    expire_at TEXT,
                    max_uses INTEGER DEFAULT 1,
                    used_count INTEGER DEFAULT 0,
                    last_used_at TEXT,
                    max_devices INTEGER DEFAULT 5,
                    devices TEXT,
                    user_note TEXT,
                    sys_platform TEXT DEFAULT '卡密系统',
                    uuid TEXT,
                    bstudio_create_time TEXT,
                    sale_status TEXT,
                    order_id TEXT,
                    sales_channel TEXT,
                    sold_at TEXT
                )
            """)
            
            # 访问日志表
            conn.execute("""
                CREATE TABLE IF NOT EXISTS access_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    card_key_id INTEGER,
                    key_value TEXT NOT NULL,
                    success INTEGER DEFAULT 0,
                    error_msg TEXT,
                    access_time TEXT DEFAULT CURRENT_TIMESTAMP,
                    access_date TEXT,
                    access_hour INTEGER,
                    device_type TEXT,
                    is_first_access INTEGER DEFAULT 0,
                    sales_channel TEXT,
                    session_duration INTEGER,
                    content_loaded INTEGER
                )
            """)
            
            # 批量操作日志表
            conn.execute("""
                CREATE TABLE IF NOT EXISTS batch_operation_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    operation_type TEXT,
                    affected_count INTEGER,
                    operator TEXT,
                    operation_time TEXT DEFAULT CURRENT_TIMESTAMP,
                    filter_conditions TEXT,
                    affected_ids TEXT,
                    update_fields TEXT,
                    remark TEXT,
                    details TEXT
                )
            """)
            
            # 创建索引
            conn.execute("CREATE INDEX IF NOT EXISTS idx_card_keys_key_value ON card_keys_table(key_value)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_card_keys_status ON card_keys_table(status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_access_logs_key_value ON access_logs(key_value)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_access_logs_access_time ON access_logs(access_time)")
            
            conn.commit()
    
    def table(self, table_name: str) -> "SQLiteTable":
        """获取表操作对象"""
        return SQLiteTable(self, table_name)


class SQLiteTable:
    """SQLite 表操作 - 模拟 Supabase Table 接口"""
    
    def __init__(self, client: SQLiteClient, table_name: str):
        self.client = client
        self.table_name = table_name
        self._filters: List[tuple] = []
        self._order_column: str = None
        self._order_desc: bool = False
        self._limit_val: int = None
        self._offset_val: int = None
        self._select_columns: str = "*"
        self._count_mode: bool = False
    
    def select(self, *columns, count: str = None) -> "SQLiteTable":
        """选择列"""
        if columns:
            self._select_columns = ", ".join(columns)
        self._count_mode = count == "exact"
        return self
    
    def eq(self, column: str, value: Any) -> "SQLiteTable":
        """等于条件"""
        self._filters.append((column, "=", value))
        return self
    
    def neq(self, column: str, value: Any) -> "SQLiteTable":
        """不等于条件"""
        self._filters.append((column, "!=", value))
        return self
    
    def in_(self, column: str, values: List[Any]) -> "SQLiteTable":
        """IN 条件"""
        self._filters.append((column, "IN", values))
        return self
    
    def like(self, column: str, pattern: str) -> "SQLiteTable":
        """LIKE 条件"""
        self._filters.append((column, "LIKE", pattern))
        return self
    
    def ilike(self, column: str, pattern: str) -> "SQLiteTable":
        """ILIKE 条件（SQLite 不支持，转为 LIKE）"""
        self._filters.append((column, "LIKE", pattern.replace("%", "").replace("_", "")))
        return self
    
    def gte(self, column: str, value: Any) -> "SQLiteTable":
        """大于等于条件"""
        self._filters.append((column, ">=", value))
        return self
    
    def lte(self, column: str, value: Any) -> "SQLiteTable":
        """小于等于条件"""
        self._filters.append((column, "<=", value))
        return self
    
    def gt(self, column: str, value: Any) -> "SQLiteTable":
        """大于条件"""
        self._filters.append((column, ">", value))
        return self
    
    def lt(self, column: str, value: Any) -> "SQLiteTable":
        """小于条件"""
        self._filters.append((column, "<", value))
        return self
    
    def is_(self, column: str, value: Any) -> "SQLiteTable":
        """IS 条件"""
        if value is None:
            self._filters.append((column, "IS", "NULL"))
        else:
            self._filters.append((column, "IS", value))
        return self
    
    def order(self, column: str, desc: bool = False) -> "SQLiteTable":
        """排序"""
        self._order_column = column
        self._order_desc = desc
        return self
    
    def limit(self, count: int) -> "SQLiteTable":
        """限制数量"""
        self._limit_val = count
        return self
    
    def offset(self, count: int) -> "SQLiteTable":
        """偏移"""
        self._offset_val = count
        return self
    
    def range(self, start: int, end: int) -> "SQLiteTable":
        """范围查询（Supabase 风格：start 到 end，包含两端）"""
        self._offset_val = start
        self._limit_val = end - start + 1
        return self
    
    def _build_where_clause(self) -> tuple:
        """构建 WHERE 子句"""
        if not self._filters:
            return "", []
        
        clauses = []
        params = []
        
        for col, op, val in self._filters:
            if op == "IN":
                placeholders = ", ".join(["?" for _ in val])
                clauses.append(f"{col} IN ({placeholders})")
                params.extend(val)
            elif op == "IS":
                clauses.append(f"{col} IS NULL")
            else:
                clauses.append(f"{col} {op} ?")
                params.append(val)
        
        return " AND ".join(clauses), params
    
    def execute(self) -> "SQLiteResponse":
        """执行查询"""
        with self.client._get_connection() as conn:
            cursor = conn.cursor()
            
            # 构建 SQL
            sql = f"SELECT {self._select_columns} FROM {self.table_name}"
            where_clause, params = self._build_where_clause()
            
            if where_clause:
                sql += f" WHERE {where_clause}"
            
            if self._order_column:
                sql += f" ORDER BY {self._order_column}"
                if self._order_desc:
                    sql += " DESC"
            
            if self._limit_val:
                sql += f" LIMIT {self._limit_val}"
            
            if self._offset_val:
                sql += f" OFFSET {self._offset_val}"
            
            cursor.execute(sql, params)
            rows = cursor.fetchall()
            
            # 转换为字典列表
            data = [dict(row) for row in rows]
            
            # 获取总数（如果需要）
            count = None
            if self._count_mode:
                count_sql = f"SELECT COUNT(*) FROM {self.table_name}"
                if where_clause:
                    count_sql += f" WHERE {where_clause}"
                cursor.execute(count_sql, params)
                count = cursor.fetchone()[0]
            
            return SQLiteResponse(data, count)
    
    def insert(self, data: Dict) -> "SQLiteInsert":
        """插入数据"""
        return SQLiteInsert(self, data)
    
    def update(self, data: Dict) -> "SQLiteUpdate":
        """更新数据"""
        return SQLiteUpdate(self, data)
    
    def delete(self) -> "SQLiteDelete":
        """删除数据"""
        return SQLiteDelete(self)


class SQLiteInsert:
    """SQLite 插入操作"""
    
    def __init__(self, table: SQLiteTable, data):
        self.table = table
        self.data = data
    
    def execute(self) -> SQLiteResponse:
        """执行插入（支持单条和批量）"""
        with self.table.client._get_connection() as conn:
            cursor = conn.cursor()
            
            # 判断是单条插入还是批量插入
            if isinstance(self.data, list):
                # 批量插入
                if not self.data:
                    return SQLiteResponse([])
                
                all_inserted = []
                for item in self.data:
                    processed_values = []
                    for v in item.values():
                        if isinstance(v, (dict, list)):
                            processed_values.append(json.dumps(v, ensure_ascii=False))
                        else:
                            processed_values.append(v)
                    
                    columns = ", ".join(item.keys())
                    placeholders = ", ".join(["?" for _ in item])
                    sql = f"INSERT INTO {self.table.table_name} ({columns}) VALUES ({placeholders})"
                    
                    cursor.execute(sql, processed_values)
                    last_id = cursor.lastrowid
                    cursor.execute(f"SELECT * FROM {self.table.table_name} WHERE id = ?", [last_id])
                    row = cursor.fetchone()
                    if row:
                        all_inserted.append(dict(row))
                
                conn.commit()
                return SQLiteResponse(all_inserted)
            else:
                # 单条插入
                processed_values = []
                for v in self.data.values():
                    if isinstance(v, (dict, list)):
                        processed_values.append(json.dumps(v, ensure_ascii=False))
                    else:
                        processed_values.append(v)
                
                columns = ", ".join(self.data.keys())
                placeholders = ", ".join(["?" for _ in self.data])
                sql = f"INSERT INTO {self.table.table_name} ({columns}) VALUES ({placeholders})"
                
                cursor.execute(sql, processed_values)
                conn.commit()
                
                # 返回插入的数据
                last_id = cursor.lastrowid
                cursor.execute(f"SELECT * FROM {self.table.table_name} WHERE id = ?", [last_id])
                row = cursor.fetchone()
                
                return SQLiteResponse([dict(row)] if row else [])


class SQLiteUpdate:
    """SQLite 更新操作"""
    
    def __init__(self, table: SQLiteTable, data: Dict):
        self.table = table
        self.data = data
        self._filters: List[tuple] = []
    
    def eq(self, column: str, value: Any) -> "SQLiteUpdate":
        """等于条件"""
        self._filters.append((column, "=", value))
        return self
    
    def in_(self, column: str, values: List[Any]) -> "SQLiteUpdate":
        """IN 条件"""
        self._filters.append((column, "IN", values))
        return self
    
    def _build_where_clause(self) -> tuple:
        """构建 WHERE 子句"""
        if not self._filters:
            return "", []
        
        clauses = []
        params = []
        
        for col, op, val in self._filters:
            if op == "IN":
                placeholders = ", ".join(["?" for _ in val])
                clauses.append(f"{col} IN ({placeholders})")
                params.extend(val)
            else:
                clauses.append(f"{col} {op} ?")
                params.append(val)
        
        return " AND ".join(clauses), params
    
    def execute(self) -> SQLiteResponse:
        """执行更新"""
        with self.table.client._get_connection() as conn:
            cursor = conn.cursor()
            
            # 先查询要更新的记录ID
            where_clause, params = self._build_where_clause()
            if where_clause:
                cursor.execute(f"SELECT id FROM {self.table.table_name} WHERE {where_clause}", params)
            else:
                cursor.execute(f"SELECT id FROM {self.table.table_name}")
            
            affected_ids = [row[0] for row in cursor.fetchall()]
            
            # 执行更新
            set_clause = ", ".join([f"{k} = ?" for k in self.data.keys()])
            sql = f"UPDATE {self.table.table_name} SET {set_clause}"
            if where_clause:
                sql += f" WHERE {where_clause}"
            
            cursor.execute(sql, list(self.data.values()) + params)
            conn.commit()
            
            # 返回更新后的记录
            if affected_ids:
                placeholders = ", ".join(["?" for _ in affected_ids])
                cursor.execute(f"SELECT * FROM {self.table.table_name} WHERE id IN ({placeholders})", affected_ids)
                rows = cursor.fetchall()
                return SQLiteResponse([dict(row) for row in rows])
            
            return SQLiteResponse([])


class SQLiteDelete:
    """SQLite 删除操作"""
    
    def __init__(self, table: SQLiteTable):
        self.table = table
        self._filters: List[tuple] = []
    
    def eq(self, column: str, value: Any) -> "SQLiteDelete":
        """等于条件"""
        self._filters.append((column, "=", value))
        return self
    
    def in_(self, column: str, values: List[Any]) -> "SQLiteDelete":
        """IN 条件"""
        self._filters.append((column, "IN", values))
        return self
    
    def _build_where_clause(self) -> tuple:
        """构建 WHERE 子句"""
        if not self._filters:
            return "", []
        
        clauses = []
        params = []
        
        for col, op, val in self._filters:
            if op == "IN":
                placeholders = ", ".join(["?" for _ in val])
                clauses.append(f"{col} IN ({placeholders})")
                params.extend(val)
            else:
                clauses.append(f"{col} {op} ?")
                params.append(val)
        
        return " AND ".join(clauses), params
    
    def execute(self) -> SQLiteResponse:
        """执行删除"""
        with self.table.client._get_connection() as conn:
            cursor = conn.cursor()
            
            where_clause, params = self._build_where_clause()
            sql = f"DELETE FROM {self.table.table_name}"
            if where_clause:
                sql += f" WHERE {where_clause}"
            
            cursor.execute(sql, params)
            conn.commit()
            
            return SQLiteResponse([])


# ============================================
# 统一数据库客户端
# ============================================

_db_client = None
_is_sqlite = False


def get_db_client():
    """获取数据库客户端（自动选择模式）"""
    global _db_client, _is_sqlite
    
    if _db_client is not None:
        return _db_client, _is_sqlite
    
    if is_production():
        # 生产环境：使用 Supabase
        from .supabase_client import get_supabase_client
        _db_client = get_supabase_client()
        _is_sqlite = False
    else:
        # 本地开发：使用 SQLite
        _db_client = SQLiteClient()
        _is_sqlite = True
    
    return _db_client, _is_sqlite


def reset_db_client():
    """重置数据库客户端（用于测试）"""
    global _db_client, _is_sqlite
    _db_client = None
    _is_sqlite = False
