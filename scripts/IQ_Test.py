import os
from dotenv import load_dotenv
from qbraid.runtime import QbraidProvider

load_dotenv()  # loads variables from a local .env file, if present

# Despite the var name, this is actually a qBraid platform key (starts with
# "qbr_"), not an IonQ Cloud key — so it goes to QbraidProvider, which routes
# to IonQ devices through qBraid's own job system and bills against qBraid
# credits, not IonQProvider (which needs a separate IonQ Cloud account key).
my_api_key = os.getenv("IONQ_TOKEN")
provider = QbraidProvider(api_key=my_api_key)

devices = provider.get_devices()
ionq_devices = [d for d in devices if "ionq" in str(d.id).lower()]
print(ionq_devices)
