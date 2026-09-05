from __future__ import annotations

from dataclasses import dataclass, field


SERVICE_NAME = "YouTubeCreatorAgent"


class CredentialStoreError(RuntimeError):
    pass


@dataclass
class CredentialStore:
    """Stores provider API keys in the operating-system credential vault.

    API keys are intentionally kept out of JSON settings and logs. Session-only
    keys can be used when the OS keyring is unavailable or the user chooses not
    to persist a credential.

    The legacy provider-wide key remains supported. Named keys are stored under
    opaque key ids so a provider can have a rotation pool without exposing
    secrets in application metadata.
    """

    service_name: str = SERVICE_NAME
    _session: dict[str, str] = field(default_factory=dict)

    @staticmethod
    def _provider(provider: str) -> str:
        normalized = provider.strip().lower()
        if not normalized:
            raise CredentialStoreError("Provedor de IA inválido.")
        return normalized

    @classmethod
    def _account(cls, provider: str) -> str:
        return f"ai:{cls._provider(provider)}:api_key"

    @classmethod
    def _named_account(cls, provider: str, key_id: str) -> str:
        key_id = (key_id or "").strip()
        if not key_id:
            raise CredentialStoreError("Identificador de chave inválido.")
        return f"ai:{cls._provider(provider)}:api_key:{key_id}"

    def _save_account(self, account: str, api_key: str) -> None:
        if not api_key:
            raise CredentialStoreError("A chave API não pode ser vazia.")
        try:
            import keyring
            from keyring.errors import KeyringError
        except ImportError as exc:
            raise CredentialStoreError(
                "O suporte ao cofre de credenciais não está instalado."
            ) from exc
        try:
            keyring.set_password(self.service_name, account, api_key)
        except KeyringError as exc:
            raise CredentialStoreError(
                "O sistema operacional não disponibilizou um cofre de credenciais utilizável."
            ) from exc
        self._session[account] = api_key

    def _get_account(self, account: str) -> str | None:
        if account in self._session:
            return self._session[account]
        try:
            import keyring
            from keyring.errors import KeyringError
        except ImportError:
            return None
        try:
            value = keyring.get_password(self.service_name, account)
        except KeyringError:
            return None
        if value:
            self._session[account] = value
        return value

    def _delete_account(self, account: str) -> None:
        self._session.pop(account, None)
        try:
            import keyring
            from keyring.errors import KeyringError, PasswordDeleteError
        except ImportError:
            return
        try:
            keyring.delete_password(self.service_name, account)
        except (KeyringError, PasswordDeleteError):
            return

    def set_session_key(self, provider: str, api_key: str) -> None:
        account = self._account(provider)
        if api_key:
            self._session[account] = api_key
        else:
            self._session.pop(account, None)

    def set_named_session_key(self, provider: str, key_id: str, api_key: str) -> None:
        account = self._named_account(provider, key_id)
        if api_key:
            self._session[account] = api_key
        else:
            self._session.pop(account, None)

    def save_key(self, provider: str, api_key: str) -> None:
        self._save_account(self._account(provider), api_key)

    def get_key(self, provider: str) -> str | None:
        return self._get_account(self._account(provider))

    def delete_key(self, provider: str) -> None:
        self._delete_account(self._account(provider))

    def save_named_key(self, provider: str, key_id: str, api_key: str) -> None:
        self._save_account(self._named_account(provider, key_id), api_key)

    def get_named_key(self, provider: str, key_id: str) -> str | None:
        return self._get_account(self._named_account(provider, key_id))

    def delete_named_key(self, provider: str, key_id: str) -> None:
        self._delete_account(self._named_account(provider, key_id))
