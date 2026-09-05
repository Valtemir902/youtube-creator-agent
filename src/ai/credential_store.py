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
    """

    service_name: str = SERVICE_NAME
    _session: dict[str, str] = field(default_factory=dict)

    @staticmethod
    def _account(provider: str) -> str:
        normalized = provider.strip().lower()
        if not normalized:
            raise CredentialStoreError("Provedor de IA inválido.")
        return f"ai:{normalized}:api_key"

    def set_session_key(self, provider: str, api_key: str) -> None:
        account = self._account(provider)
        if api_key:
            self._session[account] = api_key
        else:
            self._session.pop(account, None)

    def save_key(self, provider: str, api_key: str) -> None:
        if not api_key:
            raise CredentialStoreError("A chave API não pode ser vazia.")
        try:
            import keyring
            from keyring.errors import KeyringError
        except ImportError as exc:
            raise CredentialStoreError(
                "O suporte ao cofre de credenciais não está instalado."
            ) from exc

        account = self._account(provider)
        try:
            keyring.set_password(self.service_name, account, api_key)
        except KeyringError as exc:
            raise CredentialStoreError(
                "O sistema operacional não disponibilizou um cofre de credenciais utilizável."
            ) from exc
        self._session[account] = api_key

    def get_key(self, provider: str) -> str | None:
        account = self._account(provider)
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

    def delete_key(self, provider: str) -> None:
        account = self._account(provider)
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
