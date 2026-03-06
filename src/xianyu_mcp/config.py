"""Configuration management using pydantic-settings."""

from pathlib import Path
from typing import Literal, Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Browser Configuration
    headless: bool = Field(default=True, description="Run browser in headless mode")
    user_data_dir: Path = Field(
        default=Path("./browser_data"),
        description="Legacy browser data directory (not used for session persistence)"
    )
    page_timeout: int = Field(
        default=30000,
        description="Page operation timeout in milliseconds"
    )
    slow_mo: int = Field(
        default=0,
        description="Slow down operations by specified milliseconds (for debugging)"
    )
    cookie_auto_sync_enabled: bool = Field(
        default=True,
        description="Enable periodic cookie auto-sync and login-state cleanup",
    )
    cookie_sync_interval_seconds: int = Field(
        default=600,
        ge=60,
        description="Interval for background cookie sync in seconds (>= 60)",
    )
    cookie_sync_timeout_seconds: float = Field(
        default=30.0,
        gt=0,
        description="Timeout for each cookie sync check in seconds",
    )

    # Debug Configuration
    auto_screenshot: bool = Field(
        default=False,
        description="Automatically take screenshots after key operations"
    )
    screenshot_dir: Path = Field(
        default=Path("./screenshots"),
        description="Directory to save screenshots (Docker 环境请映射到宿主机)"
    )

    # Logging Configuration
    log_level: str = Field(
        default="INFO",
        description="Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)"
    )

    # MCP Configuration
    mcp_transport: Literal["stdio", "streamable_http"] = Field(
        default="streamable_http",
        description="MCP transport mode: stdio or streamable_http"
    )
    mcp_tool_timeout_seconds: float = Field(
        default=10.0,
        gt=0,
        description="Timeout for each MCP tool call in seconds"
    )
    mcp_http_host: str = Field(
        default="127.0.0.1",
        description="Host for Streamable HTTP transport"
    )
    mcp_http_port: int = Field(
        default=18000,
        ge=1,
        le=65535,
        description="Port for Streamable HTTP transport"
    )
    mcp_streamable_http_path: str = Field(
        default="/mcp",
        description="HTTP path for Streamable HTTP MCP endpoint"
    )



# Global settings instance
_settings: Optional[Settings] = None


def get_settings() -> Settings:
    """Get the global settings instance."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings



