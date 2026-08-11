from memory import memory


USER_ID = "sharvesh"


print("Adding memories...")

memory.add(
    "My name is Sharvesh.",
    user_id=USER_ID
)

memory.add(
    "I am building a local AI assistant called MOSHI.",
    user_id=USER_ID
)

memory.add(
    "MOSHI uses LM Studio for local AI models.",
    user_id=USER_ID
)

print("Memories added.")


print("\nSearching memory...")

results = memory.search(
    "What is Sharvesh building?",
    filters={
        "user_id": USER_ID
    }
)
print("\nRAW RESULTS:")
print(results)

print("\nMEMORIES:")

for result in results.get("results", []):
    print("-", result.get("memory"))