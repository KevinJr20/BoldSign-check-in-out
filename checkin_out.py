import os
import requests
from typing import List, Dict
from requests.exceptions import HTTPError, RequestException
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configuration from environment variables
API_TOKEN = os.getenv("BOLDSIGN_API_TOKEN", "your_api_token")
BASE_URL = os.getenv("BOLDSIGN_BASE_URL", "https://staging-app.boldsign.com")
HEADERS = {"Authorization": f"Bearer {API_TOKEN}", "Content-Type": "application/json"}

# Debug: Print configuration
print(f"Using BASE_URL: {BASE_URL}")
print(f"API_TOKEN (first 5 chars): {API_TOKEN[:5]}...")

def create_template() -> str:
    """Create a reusable check-in/out template."""
    try:
        payload = {
            "title": "Syncfusion Employee Check-In/Out",
            "description": "Daily employee check-in/out form for Syncfusion",
            "document": {
                "pages": [{"fields": [
                    {"type": "text", "name": "name", "isRequired": True, "x": 50, "y": 50},
                    {"type": "text", "name": "employee_id", "isRequired": True, "x": 50, "y": 100},
                    {"type": "date", "name": "date", "isRequired": True, "x": 50, "y": 150},
                    {"type": "text", "name": "time_in", "isRequired": False, "x": 50, "y": 200},
                    {"type": "text", "name": "time_out", "isRequired": False, "x": 50, "y": 250},
                    {"type": "signature", "name": "signature", "isRequired": True, "x": 50, "y": 300}
                ]}]
            }
        }
        response = requests.post(f"{BASE_URL}/template/create", headers=HEADERS, json=payload)
        response.raise_for_status()
        return response.json()["templateId"]
    except HTTPError as e:
        print(f"HTTP Error: {e.response.status_code} - {e.response.text}")
        raise Exception(f"Failed to create template: {str(e)}")
    except RequestException as e:
        print(f"Request Error: {str(e)}")
        raise Exception(f"Failed to create template: {str(e)}")

def create_signing_document(template_id: str, employees: List[Dict]) -> List[str]:
    """Create signing documents for multiple employees."""
    try:
        signing_urls = []
        for employee in employees:
            payload = {
                "templateId": template_id,
                "signers": [{
                    "name": employee["name"],
                    "emailAddress": employee["email"],
                    "formFields": [
                        {"name": "name", "value": employee["name"]},
                        {"name": "employee_id", "value": employee["id"]},
                        {"name": "date", "value": "2025-04-16"}
                    ]
                }],
                "embeddedSigningLink": True
            }
            response = requests.post(f"{BASE_URL}/document/create", headers=HEADERS, json=payload)
            response.raise_for_status()
            signing_urls.append(response.json()["signingUrl"])
        return signing_urls
    except HTTPError as e:
        print(f"HTTP Error: {e.response.status_code} - {e.response.text}")
        raise Exception(f"Failed to create document: {str(e)}")
    except RequestException as e:
        print(f"Request Error: {str(e)}")
        raise Exception(f"Failed to create document: {str(e)}")

def create_webhook(webhook_url: str) -> str:
    """Configure a webhook for document completion events."""
    try:
        payload = {
            "event": "document.completed",
            "url": webhook_url
        }
        response = requests.post(f"{BASE_URL}/webhook/create", headers=HEADERS, json=payload)
        response.raise_for_status()
        return response.json()["webhookId"]
    except HTTPError as e:
        print(f"HTTP Error: {e.response.status_code} - {e.response.text}")
        raise Exception(f"Failed to create webhook: {str(e)}")
    except RequestException as e:
        print(f"Request Error: {str(e)}")
        raise Exception(f"Failed to create webhook: {str(e)}")

if __name__ == "__main__":
    # Demo employee data
    employees = [
        {"name": "Kevin Omondi", "email": "kevinjr1@syncfusion.com", "id": "SFK000"},
        {"name": "Rudolph Melvin", "email": "rudolphm@syncfusion.com", "id": "SFK001"}
    ]

    try:
        # Create template, documents, and webhook
        template_id = create_template()
        signing_urls = create_signing_document(template_id, employees)
        webhook_id = create_webhook("https://syncfusion-hr.com/attendance")
        for url in signing_urls:
            print(f"Signing URL: {url}")
        print(f"Webhook ID: {webhook_id}")
    except Exception as e:
        print(f"Error: {str(e)}")