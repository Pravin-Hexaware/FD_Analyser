import requests
from azure.identity import DefaultAzureCredential
from azure.keyvault.secrets import SecretClient
from requests.exceptions import HTTPError, JSONDecodeError

# Key Vault URL
key_vault_url = "https://fstodevazureopenai.vault.azure.net/"

# Authenticate using DefaultAzureCredential
credential = DefaultAzureCredential()

# Create a SecretClient to interact with the Key Vault
client = SecretClient(vault_url=key_vault_url, credential=credential)

# Secret names (make sure these secrets exist in your Key Vault)
secret_names = ["llm-base-endpoint", "llm-mini", "llm-mini-version", "llm-api-key"]

# Retrieve secrets from the Key Vault with exception handling
secrets = {}
for secret_name in secret_names:
    try:
        secret = client.get_secret(secret_name)
        secrets[secret_name] = secret.value
    except Exception as e:
        print(f"Error retrieving secret '{secret_name}': {e}")
        raise


def call_llm(prompt):
    base_url = secrets.get("llm-base-endpoint")  # Should be like https://fs-crewai-openai.openai.azure.com
    deployment = secrets.get("llm-mini")
    version = secrets.get("llm-mini-version")
    api_key = secrets.get("llm-api-key")

    if not all([base_url, deployment, version, api_key]):
        raise ValueError("One or more required secrets are missing.")

    payload = {
        "messages": [
            {"role": "user", "content": prompt}
        ]
    }

    headers = {
        "Content-Type": "application/json",
        "api-key": api_key
    }

    full_url = f"{base_url}openai/deployments/{deployment}/chat/completions?api-version={version}"
    response = ""
    try:
        response = requests.post(full_url, json=payload, headers=headers)
        response.raise_for_status()
        return response.json()
    except HTTPError as http_err:
        print(f"HTTP error occurred: {http_err}")
        print(f"Response content: {response.text}")
        raise
    except JSONDecodeError as json_err:
        print(f"JSON decode error: {json_err}")
        print(f"Response content (not JSON): {response.text}")
        raise
    except Exception as err:
        print(f"An error occurred during the HTTP request: {err}")
        raise


if __name__ == "__main__":
    prompt_text = "Hello, what's the capital of Canada?"
    try:
        result = call_llm(prompt_text)
        print("LLM Response:", result)
    except Exception as e:
        print(f"Failed to call LLM: {e}")
