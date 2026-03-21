from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, JSON, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from typing import Optional
from datetime import datetime
from coze_coding_dev_sdk.database import Base


class HealthCheck(Base):
    """系统健康检查表 - 由系统自动创建，禁止删除"""
    __tablename__ = "health_check"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class CardType(Base):
    """卡种表 - 卡密分组管理"""
    __tablename__ = "card_types"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    
    # 基础信息
    name: Mapped[str] = mapped_column(String(200), nullable=False, comment="卡种名称")
    
    # 过期设置
    expire_type: Mapped[Optional[str]] = mapped_column(String(20), nullable=True, comment="过期类型: fixed=固定日期, relative=按激活天数, permanent=永久")
    expire_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True, comment="过期时间(固定日期)")
    expire_after_days: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, comment="激活后有效天数")
    
    # 飞书内容
    feishu_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="飞书链接")
    feishu_password: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, comment="飞书访问密码")
    link_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, comment="链接名称")
    
    # 设备限制
    max_devices: Mapped[int] = mapped_column(Integer, default=5, nullable=False, comment="最大设备数")
    
    # 预览设置
    preview_image: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="预览截图URL")
    preview_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, comment="是否启用预览")
    
    # 状态
    status: Mapped[int] = mapped_column(Integer, default=1, nullable=False, comment="状态: 1=有效, 0=无效")
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True, comment="软删除时间")
    
    # 时间戳
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False, comment="创建时间")
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), onupdate=func.now(), nullable=True, comment="更新时间")
    
    __table_args__ = (
        Index("ix_card_types_name", "name"),
        Index("ix_card_types_status", "status"),
    )


class CardKey(Base):
    """卡密表"""
    __tablename__ = "card_keys_table"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    
    # 基础信息
    key_value: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, comment="卡密值")
    status: Mapped[int] = mapped_column(Integer, default=1, nullable=False, comment="状态: 1=有效, 0=无效")
    
    # 卡种关联
    card_type_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("card_types.id"), nullable=True, comment="卡种ID")
    
    # 飞书内容
    feishu_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="飞书链接")
    feishu_password: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, comment="飞书访问密码")
    link_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, comment="链接名称")
    
    # 过期与使用限制
    expire_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True, comment="过期时间(固定日期)")
    expire_after_days: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, comment="激活后有效天数")
    activated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True, comment="首次激活时间")
    max_uses: Mapped[int] = mapped_column(Integer, default=1, nullable=False, comment="最大使用次数（已废弃）")
    used_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="已使用次数（已废弃）")
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True, comment="最后使用时间")
    
    # 设备限制
    max_devices: Mapped[int] = mapped_column(Integer, default=5, nullable=False, comment="最大设备数")
    devices: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="已绑定设备ID列表(JSON)")
    
    # 备注信息
    user_note: Mapped[Optional[str]] = mapped_column(String(200), nullable=True, comment="用户备注")
    sys_platform: Mapped[str] = mapped_column(String(50), default='卡密系统', nullable=False, comment="来源平台")
    
    # 时间戳
    uuid: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    bstudio_create_time: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True, comment="创建时间")
    
    __table_args__ = (
        Index("ix_card_keys_key_value", "key_value"),
        Index("ix_card_keys_status", "status"),
        Index("ix_card_keys_card_type_id", "card_type_id"),
    )


class AccessLog(Base):
    """访问日志表"""
    __tablename__ = "access_logs"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    
    # 卡密信息
    card_key_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("card_keys_table.id"), nullable=True, comment="卡密ID")
    key_value: Mapped[str] = mapped_column(String(50), nullable=False, comment="卡密值")
    
    # 注意：根据《个人信息保护法》合规要求，不再收集IP地址、User-Agent、设备类型
    
    # 结果
    success: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, comment="是否成功")
    error_msg: Mapped[Optional[str]] = mapped_column(String(200), nullable=True, comment="错误信息")
    
    # 时间
    access_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False, comment="访问时间")
    
    # 会话追踪
    session_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, comment="会话ID")
    
    __table_args__ = (
        Index("ix_access_logs_key_value", "key_value"),
        Index("ix_access_logs_access_time", "access_time"),
        Index("ix_access_logs_card_key_id", "card_key_id"),
    )


class LinkHealth(Base):
    """链接健康状态表"""
    __tablename__ = "link_health_table"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    
    # 链接信息
    feishu_url: Mapped[str] = mapped_column(Text, nullable=False, comment="飞书链接")
    link_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True, comment="链接名称")
    
    # 健康状态
    status: Mapped[str] = mapped_column(String(20), default='unknown', nullable=False, comment="状态: healthy=正常, unhealthy=失效, unknown=未知")
    http_code: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, comment="HTTP状态码")
    error_message: Mapped[Optional[str]] = mapped_column(String(500), nullable=True, comment="错误信息")
    
    # 检测时间
    last_check_time: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True, comment="最后检测时间")
    next_check_time: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True, comment="下次检测时间")
    
    # 统计
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="连续失败次数")
    total_checks: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="总检测次数")
    successful_checks: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="成功检测次数")
    
    # 时间戳
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False, comment="创建时间")
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), onupdate=func.now(), nullable=True, comment="更新时间")
    
    __table_args__ = (
        Index("ix_link_health_feishu_url", "feishu_url"),
        Index("ix_link_health_status", "status"),
        Index("ix_link_health_next_check_time", "next_check_time"),
    )
