import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
from azure.identity import DefaultAzureCredential
from azure.keyvault.secrets import SecretClient

from llm.azure_llm import KEY_VAULT_URL, evaluate_with_azure_llm

load_dotenv()

CACHE_DIR = Path("cache")
CACHE_DIR.mkdir(exist_ok=True)


def fetch_secret(secret_name: str, vault_url: str = KEY_VAULT_URL) -> str:
    credential = DefaultAzureCredential()
    client = SecretClient(vault_url=vault_url, credential=credential)
    secret = client.get_secret(secret_name)
    value = secret.value
    print(f"[SECRET] {secret_name} = {value[:4]}... (length={len(value)})")
    return value


def list_secrets(vault_url: str = KEY_VAULT_URL):
    credential = DefaultAzureCredential()
    client = SecretClient(vault_url=vault_url, credential=credential)
    names = []
    print(f"[SECRET LIST] Listing secrets from {vault_url}")
    for secret_property in client.list_properties_of_secrets():
        names.append(secret_property.name)
        print(f"- {secret_property.name}")
    if not names:
        print("[SECRET LIST] No secrets found.")
    return names


def ask_question(question: str, cache_path: Path = CACHE_DIR / "azure_probe.md") -> Any:
    prompt = f"Answer this short question concisely:\n\n{question}"
    result = evaluate_with_azure_llm(
        prompt=prompt,
        cache_path=str(cache_path),
        temperature=1.0
    )
    print("[LLM ANSWER]", result)
    return result


def print_usage():
    print("Usage:")
    print("  python tools/azure_probe.py ask \"Your question\"")
    print("  python tools/azure_probe.py secret <secret-name>")
    print("  python tools/azure_probe.py list")
    print("  python tools/azure_probe.py help")
    print("  python tools/azure_probe.py")
    print("    (interactive mode: type 'help' or your question")


def handle_input(command: str, args: list[str]):
    if command == "ask":
        if len(args) < 1:
            print("Error: missing question")
            print_usage()
            sys.exit(1)
        ask_question(" ".join(args).strip())
    elif command == "secret":
        if len(args) != 1:
            print("Error: missing secret name")
            print_usage()
            sys.exit(1)
        fetch_secret(args[0])
    elif command == "list":
        list_secrets()
    elif command in {"help", "-h", "--help"}:
        print_usage()
    else:
        print(f"Unknown command: {command}")
        print_usage()
        sys.exit(1)


if __name__ == "__main__":
    if len(sys.argv) == 1:
        user_input = input("Enter 'help' or a question: ").strip()
        if not user_input:
            print_usage()
            sys.exit(0)
        if user_input.lower() in {"help", "-h", "--help"}:
            print_usage()
            sys.exit(0)
        ask_question(user_input)

    else:
        command = sys.argv[1].lower()
        handle_input(command, sys.argv[2:])
