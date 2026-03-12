import os
import requests
import time
from flask import Flask, request, jsonify
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

TOKEN = os.getenv("HUBSPOT_TOKEN")

headers = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type": "application/json"
}

# Store processed events (to avoid duplicates)
processed_events = set()


@app.route("/webhook", methods=["POST"])
def webhook():

    try:

        events = request.get_json()

        print("\nWebhook received:", events)

        for event in events:

            event_id = event.get("eventId")
            object_id = event.get("objectId")
            object_type = event.get("objectTypeId")
            occurred_at = event.get("occurredAt")

            # Ignore duplicate events
            if event_id in processed_events:
                print("Duplicate event ignored:", event_id)
                continue

            processed_events.add(event_id)

            # Ignore old events (>60 seconds)
            now = int(time.time() * 1000)

            if occurred_at and (now - occurred_at > 60000):
                print("Old event ignored:", event_id)
                continue

            print("Processing activity object:", object_id)

            # --------------------------------
            # Get associated contact
            # --------------------------------

            assoc_url = f"https://api.hubapi.com/crm/v3/objects/{object_type}/{object_id}/associations/contacts"

            assoc_res = requests.get(assoc_url, headers=headers)

            if assoc_res.status_code != 200:
                print("Association fetch failed:", assoc_res.text)
                continue

            assoc_data = assoc_res.json().get("results", [])

            if not assoc_data:
                print("No contact associated")
                continue

            contact_id = assoc_data[0]["id"]

            print("Associated contact:", contact_id)

            # --------------------------------
            # Search latest engagement
            # --------------------------------

            search_url = "https://api.hubapi.com/crm/v3/objects/engagements/search"

            body = {
                "filterGroups": [
                    {
                        "filters": [
                            {
                                "propertyName": "associations.contact",
                                "operator": "EQ",
                                "value": contact_id
                            }
                        ]
                    }
                ],
                "sorts": [
                    {
                        "propertyName": "hs_timestamp",
                        "direction": "DESCENDING"
                    }
                ],
                "properties": [
                    "hs_timestamp",
                    "hs_engagement_type",
                    "hubspot_owner_id",
                    "hs_meeting_title",
                    "hs_meeting_start_time"
                ],
                "limit": 1
            }

            response = requests.post(search_url, headers=headers, json=body)

            if response.status_code != 200:
                print("Engagement search failed:", response.text)
                continue

            results = response.json().get("results", [])

            summary = "No activity performed"

            if results:

                activity = results[0]["properties"]

                # Detect activity type using objectTypeId (more reliable)

                object_type_map = {
                    "0-46": "Note",
                    "0-47": "Meeting",
                    "0-48": "Call",
                    "0-49": "Email",
                    "0-27": "Task"
                }

                activity_type = object_type_map.get(object_type, "Activity")

                activity_time = activity.get("hs_timestamp")

                formatted_date = ""

                if activity_time:
                    try:
                        dt = datetime.fromisoformat(activity_time.replace("Z", ""))
                        formatted_date = dt.strftime("%d %b %Y")
                    except:
                        pass

                owner_name = "Unknown"
                owner_id = activity.get("hubspot_owner_id")

                if owner_id:

                    owner_url = f"https://api.hubapi.com/crm/v3/owners/{owner_id}"

                    owner_res = requests.get(owner_url, headers=headers)

                    if owner_res.status_code == 200:

                        owner_data = owner_res.json()

                        owner_name = owner_data.get("firstName", "Unknown")

                summary = f"{activity_type} by {owner_name} on {formatted_date}"

            print("Generated summary:", summary)

            # --------------------------------
            # Update contact property
            # --------------------------------

            update_url = f"https://api.hubapi.com/crm/v3/objects/contacts/{contact_id}"

            update_data = {
                "properties": {
                    "last_engagement_summary": summary
                }
            }

            update_res = requests.patch(update_url, headers=headers, json=update_data)

            if update_res.status_code != 200:
                print("Update failed:", update_res.text)
            else:
                print("Contact updated successfully")

        return jsonify({"status": "ok"}), 200

    except Exception as e:

        print("Error:", str(e))

        return jsonify({"error": str(e)}), 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)