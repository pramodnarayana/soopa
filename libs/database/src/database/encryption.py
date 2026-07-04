import os

import structlog
from cryptography.fernet import Fernet, InvalidToken

logger = structlog.get_logger(__name__)


class DBEncryptionAdapter:
    def __init__(self) -> None:
        self._fernet: Fernet | None = None
        self._initialized = False

    @property
    def fernet(self) -> Fernet | None:
        if not self._initialized:
            key = os.getenv("DB_ENCRYPTION_KEY")
            if not key:
                logger.warning("DB_ENCRYPTION_KEY is not set. Database encryption will fail.")
                self._fernet = None
            else:
                try:
                    self._fernet = Fernet(key.encode("utf-8"))
                except Exception as e:
                    logger.error(f"Failed to initialize Fernet with provided key: {e}")
                    self._fernet = None
            self._initialized = True
        return self._fernet

    def encrypt(self, data: str) -> str:
        if not self.fernet:
            raise RuntimeError("DB_ENCRYPTION_KEY not configured")
        return self.fernet.encrypt(data.encode("utf-8")).decode("utf-8")

    def decrypt(self, token: str) -> str:
        if not self.fernet:
            raise RuntimeError("DB_ENCRYPTION_KEY not configured")
        try:
            return self.fernet.decrypt(token.encode("utf-8")).decode("utf-8")
        except InvalidToken:
            logger.error("Failed to decrypt database field. Invalid token.")
            raise


db_encryption = DBEncryptionAdapter()
