from anthropic import Anthropic
from dotenv import load_dotenv
import json

load_dotenv()

client = Anthropic()

message = client.messages.create(
    model="claude-sonnet-4-5",
    max_tokens=1024,
    system="You return JSON only. No prose, no preamble, no code fences. Schema: {\"fact\": string, \"animal\": string, \"surprising\": boolean}",
    messages=[
        {"role": "user", "content": "Give me one fact about octopuses."}
    ]
)

raw = message.content[0].text
data = json.loads(raw)
print(f"Animal: {data['animal']}")
print(f"Fact: {data['fact']}")
print(f"Surprising? {data['surprising']}")
