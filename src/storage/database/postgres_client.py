"""
PostgreSQL 直连客户端 - 模拟 Supabase 接口

支持两种连接方式：
1. DATABASE_URL：完整的 PostgreSQL 连接字符串
2. 分离参数：PGHOST, PGPORT, PGDATABASE, PGUSER, PGPASSWORD

扣子平台会自动注入这些环境变量，开发环境和生产环境自动切换
"""

import os
import json
from typing import Optional, Any, Dict, List
import psycopg2
from psycopg2.extras import RealDictCursor
from contextlib import contextmanager
from urllib.parse import quote_plus


class PostgresResponse:
    """模拟 Supabase Response"""
    
    def __init__(self, data: List[Dict], count: int = None):
        self.data = data
        self.count = count


class PostgresNotWrapper:
    """NOT 条件包装器"""
    
    def __init__(self, table: "PostgresTable"):
        self.table = table
    
    def in_(self, column: str, values: List[Any]) -> "PostgresTable":
        """NOT IN 条件"""
        self.table._filters.append((column, "NOT IN", values))
        return self.table
    
    def is_(self, column: str, value: Any) -> "PostgresTable":
        """IS NOT 条件"""
        if value is None or value == 'null':
            self.table._filters.append((column, "IS NOT", "NULL"))
        else:
            self.table._filters.append((column, "IS NOT", value))
        return self.table


class PostgresTable:
    """PostgreSQL 表操作 - 模拟 Supabase 接口"""
    
    def __init__(self, client: "PostgresClient", table_name: str):
        self.client = client
        self.table_name = table_name
        self._filters: List[tuple] = []
        self._or_conditions: str = None
        self._order_column: str = None
        self._order_desc: bool = False
        self._limit_val: int = None
        self._offset_val: int = 0
        self._select_columns: str = "*"
        self._count_mode: bool = False
    
    def select(self, columns: str = "*", count: str = None) -> "PostgresTable":
        """选择列"""
        self._select_columns = columns
        if count == "exact":
            self._count_mode = True
        return self
    
    def insert(self, data: Dict) -> "PostgresTable":
        """插入数据"""
        self._insert_data = data
        return self
    
    def update(self, data: Dict) -> "PostgresTable":
        """更新数据"""
        self._update_data = data
        return self
    
    def delete(self) -> "PostgresTable":
        """删除数据"""
        self._delete_mode = True
        return self
    
    def eq(self, column: str, value: Any) -> "PostgresTable":
        """等于条件"""
        self._filters.append((column, "=", value))
        return self
    
    def neq(self, column: str, value: Any) -> "PostgresTable":
        """不等于条件"""
        self._filters.append((column, "!=", value))
        return self
    
    def gt(self, column: str, value: Any) -> "PostgresTable":
        """大于条件"""
        self._filters.append((column, ">", value))
        return self
    
    def gte(self, column: str, value: Any) -> "PostgresTable":
        """大于等于条件"""
        self._filters.append((column, ">=", value))
        return self
    
    def lt(self, column: str, value: Any) -> "PostgresTable":
        """小于条件"""
        self._filters.append((column, "<", value))
        return self
    
    def lte(self, column: str, value: Any) -> "PostgresTable":
        """小于等于条件"""
        self._filters.append((column, "<=", value))
        return self
    
    def like(self, column: str, pattern: str) -> "PostgresTable":
        """LIKE 条件"""
        self._filters.append((column, "LIKE", pattern))
        return self
    
    def ilike(self, column: str, pattern: str) -> "PostgresTable":
        """ILIKE 条件（不区分大小写）"""
        self._filters.append((column, "ILIKE", pattern))
        return self
    
    def in_(self, column: str, values: List[Any]) -> "PostgresTable":
        """IN 条件"""
        self._filters.append((column, "IN", values))
        return self
    
    def is_(self, column: str, value: Any) -> "PostgresTable":
        """IS 条件"""
        if value is None:
            self._filters.append((column, "IS", "NULL"))
        else:
            self._filters.append((column, "IS", value))
        return self
    
    def not_(self) -> PostgresNotWrapper:
        """NOT 条件包装器"""
        return PostgresNotWrapper(self)
    
    def or_(self, conditions: str) -> "PostgresTable":
        """OR 条件"""
        self._or_conditions = conditions
        return self
    
    def order(self, column: str, desc: bool = False) -> "PostgresTable":
        """排序"""
        self._order_column = column
        self._order_desc = desc
        return self
    
    def limit(self, count: int) -> "PostgresTable":
        """限制数量"""
        self._limit_val = count
        return self
    
    def offset(self, count: int) -> "PostgresTable":
        """偏移"""
        self._offset_val = count
        return self
    
    def range(self, start: int, end: int) -> "PostgresTable":
        """范围查询（Supabase 风格）"""
        self._offset_val = start
        self._limit_val = end - start + 1
        return self
    
    def _build_where_clause(self) -> tuple:
        """构建 WHERE 子句"""
        clauses = []
        params = []
        
        for col, op, val in self._filters:
            if op == "IN":
                placeholders = ", ".join(["%s" for _ in val])
                clauses.append(f"{col} IN ({placeholders})")
                params.extend(val)
            elif op == "NOT IN":
                placeholders = ", ".join(["%s" for _ in val])
                clauses.append(f"{col} NOT IN ({placeholders})")
                params.extend(val)
            elif op in ("IS", "IS NOT"):
                clauses.append(f"{col} {op} {val}")
            elif op == "ILIKE":
                clauses.append(f"{col} ILIKE %s")
                params.append(val)
            elif op == "LIKE":
                clauses.append(f"{col} LIKE %s")
                params.append(val)
            else:
                clauses.append(f"{col} {op} %s")
                params.append(val)
        
        if self._or_conditions:
            or_clause = self._parse_or_conditions(self._or_conditions)
            clauses.append(or_clause)
        
        if not clauses:
            return "", params
        
        return " AND ".join(clauses), params
    
    def _parse_or_conditions(self, conditions: str) -> str:
        """解析 OR 条件
        
        格式: col1.op1.val1,col2.op2.val2,...
        其中 op 可以是 eq, in, is, ilike, like, neq, gt, gte, lt, lte
        
        注意：值中可能包含逗号（如 ilike 的值），需要智能分割
        """
        import re
        
        or_parts = []
        
        # 使用正则表达式匹配每个条件
        # 模式：字段名.操作符.值（值不包含下一个 "字段名.操作符." 模式）
        # 更好的方法：按 ",字段名." 分割
        
        # 首先，找出所有条件的起始位置
        # 条件格式：字段名.操作符.
        condition_starts = []
        for match in re.finditer(r',(\w+)\.(eq|in|is|ilike|like|neq|gt|gte|lt|lte)\.', conditions):
            condition_starts.append(match.start())
        
        # 根据起始位置分割条件
        if condition_starts:
            # 第一个条件从开始到第一个逗号
            first_end = condition_starts[0]
            condition_parts = [conditions[:first_end]]
            
            # 中间的条件
            for i in range(len(condition_starts)):
                start = condition_starts[i] + 1  # 跳过逗号
                end = condition_starts[i + 1] if i + 1 < len(condition_starts) else len(conditions)
                condition_parts.append(conditions[start:end])
        else:
            condition_parts = [conditions]
        
        # 解析每个条件
        for part in condition_parts:
            part = part.strip()
            
            # 匹配字段名.操作符.值
            match = re.match(r'(\w+)\.(eq|in|is|ilike|like|neq|gt|gte|lt|lte)\.(.+)', part)
            if match:
                col = match.group(1)
                op = match.group(2)
                val = match.group(3)
                
                # 构建条件
                if op == "eq":
                    if val.lower() in ('true', 'false'):
                        or_parts.append(f"{col} = {val.lower()}")
                    else:
                        or_parts.append(f"{col} = '{val}'")
                elif op == "neq":
                    or_parts.append(f"{col} != '{val}'")
                elif op == "in":
                    if val.startswith("(") and val.endswith(")"):
                        values = val[1:-1].split(",")
                        values_str = ", ".join([f"'{v.strip()}'" for v in values])
                        or_parts.append(f"{col} IN ({values_str})")
                elif op == "is":
                    if val == "null":
                        or_parts.append(f"{col} IS NULL")
                    else:
                        or_parts.append(f"{col} IS {val}")
                elif op == "ilike":
                    or_parts.append(f"{col} ILIKE '{val}'")
                elif op == "like":
                    or_parts.append(f"{col} LIKE '{val}'")
                elif op == "gt":
                    or_parts.append(f"{col} > '{val}'")
                elif op == "gte":
                    or_parts.append(f"{col} >= '{val}'")
                elif op == "lt":
                    or_parts.append(f"{col} < '{val}'")
                elif op == "lte":
                    or_parts.append(f"{col} <= '{val}'")
        
        return "(" + " OR ".join(or_parts) + ")" if or_parts else ""
    
    def execute(self) -> PostgresResponse:
        """执行查询"""
        with self.client._get_connection() as conn:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            
            # 检查是否有插入操作
            if hasattr(self, '_insert_data'):
                return self._execute_insert(cur, conn)
            
            # 检查是否有更新操作
            if hasattr(self, '_update_data'):
                return self._execute_update(cur, conn)
            
            # 检查是否有删除操作
            if hasattr(self, '_delete_mode') and self._delete_mode:
                return self._execute_delete(cur, conn)
            
            # SELECT 查询
            return self._execute_select(cur)
    
    def _execute_select(self, cur) -> PostgresResponse:
        """执行 SELECT 查询"""
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
        
        # 执行查询 - 如果有参数则使用参数化查询，否则直接执行
        if params:
            cur.execute(sql, params)
        else:
            cur.execute(sql)
        rows = cur.fetchall()
        
        # 转换为字典列表
        data = [dict(row) for row in rows]
        
        # 如果需要计数
        count = None
        if self._count_mode:
            count_sql = f"SELECT COUNT(*) as count FROM {self.table_name}"
            if where_clause:
                count_sql += f" WHERE {where_clause}"
            if params:
                cur.execute(count_sql, params)
            else:
                cur.execute(count_sql)
            count = cur.fetchone()['count']
        
        return PostgresResponse(data, count)
    
    def _execute_insert(self, cur, conn) -> PostgresResponse:
        """执行 INSERT"""
        data = self._insert_data
        columns = ", ".join(data.keys())
        placeholders = ", ".join(["%s" for _ in data])
        
        sql = f"INSERT INTO {self.table_name} ({columns}) VALUES ({placeholders}) RETURNING *"
        cur.execute(sql, list(data.values()))
        conn.commit()
        
        row = cur.fetchone()
        return PostgresResponse([dict(row)] if row else [], 1)
    
    def _execute_update(self, cur, conn) -> PostgresResponse:
        """执行 UPDATE"""
        data = self._update_data
        set_clause = ", ".join([f"{k} = %s" for k in data.keys()])
        
        sql = f"UPDATE {self.table_name} SET {set_clause}"
        
        where_clause, params = self._build_where_clause()
        if where_clause:
            sql += f" WHERE {where_clause}"
        
        sql += " RETURNING *"
        
        cur.execute(sql, list(data.values()) + params)
        conn.commit()
        
        rows = cur.fetchall()
        return PostgresResponse([dict(row) for row in rows], len(rows))
    
    def _execute_delete(self, cur, conn) -> PostgresResponse:
        """执行 DELETE"""
        sql = f"DELETE FROM {self.table_name}"
        
        where_clause, params = self._build_where_clause()
        if where_clause:
            sql += f" WHERE {where_clause}"
        
        sql += " RETURNING *"
        
        cur.execute(sql, params)
        conn.commit()
        
        rows = cur.fetchall()
        return PostgresResponse([dict(row) for row in rows], len(rows))


class PostgresClient:
    """PostgreSQL 客户端 - 模拟 Supabase 接口"""
    
    def __init__(self, database_url: str):
        self.database_url = database_url
        self.supabase_url = None  # 用于兼容
        
        # 添加连接超时参数（防止连接卡住）
        if '?' in database_url:
            self.database_url = database_url + '&connect_timeout=10'
        else:
            self.database_url = database_url + '?connect_timeout=10'
    
    @contextmanager
    def _get_connection(self):
        """获取数据库连接"""
        conn = psycopg2.connect(self.database_url, connect_timeout=10)
        try:
            yield conn
        finally:
            conn.close()
    
    def table(self, table_name: str) -> PostgresTable:
        """获取表操作对象"""
        return PostgresTable(self, table_name)
    
    def rpc(self, function_name: str, params: dict) -> PostgresResponse:
        """调用存储过程（暂不支持）"""
        raise NotImplementedError(f"RPC function '{function_name}' is not supported")


def get_database_url() -> Optional[str]:
    """获取数据库连接 URL
    
    支持两种方式：
    1. DATABASE_URL 或 PGDATABASE_URL：完整的连接字符串
    2. 分离参数：PGHOST, PGPORT, PGDATABASE, PGUSER, PGPASSWORD
    """
    # 方式1：完整的连接字符串
    url = os.getenv("DATABASE_URL") or os.getenv("PGDATABASE_URL")
    if url:
        return url
    
    # 方式2：从分离参数构建连接字符串
    pghost = os.getenv("PGHOST")
    pgport = os.getenv("PGPORT", "5432")
    pgdatabase = os.getenv("PGDATABASE")
    pguser = os.getenv("PGUSER")
    pgpassword = os.getenv("PGPASSWORD")
    
    if pghost and pgdatabase and pguser:
        # 对密码进行 URL 编码
        password_part = f":{quote_plus(pgpassword)}" if pgpassword else ""
        return f"postgresql://{pguser}{password_part}@{pghost}:{pgport}/{pgdatabase}"
    
    return None


def _load_env() -> None:
    """加载环境变量
    
    注意：环境变量已在 main.py 中加载，此函数主要用于：
    1. 尝试从 coze_workload_identity 获取项目环境变量（云端部署）
    2. 不再调用 load_dotenv()，避免覆盖已设置的环境变量
    """
    # 如果已经有数据库配置，跳过 coze_workload_identity 调用（避免超时）
    if os.getenv("DATABASE_URL") or os.getenv("PGDATABASE_URL"):
        return
    
    try:
        from coze_workload_identity import Client as WorkloadClient
        client = WorkloadClient()
        env_vars = client.get_project_env_vars()
        client.close()
        
        for env_var in env_vars:
            # 只设置未存在的环境变量，不覆盖已有的
            if not os.getenv(env_var.key):
                os.environ[env_var.key] = env_var.value
    except Exception:
        pass


def get_postgres_client() -> PostgresClient:
    """获取 PostgreSQL 客户端"""
    url = get_database_url()
    if not url:
        raise ValueError("DATABASE_URL or PGDATABASE_URL is not set")
    return PostgresClient(url)
