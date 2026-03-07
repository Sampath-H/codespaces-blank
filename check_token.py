import os
try:
    import streamlit as st
    secrets = dict(st.secrets)
except:
    secrets = {}

print("ENV UPSTOX_ACCESS_TOKEN:", os.environ.get("UPSTOX_ACCESS_TOKEN"))
print("SECRETS UPSTOX_ACCESS_TOKEN:", secrets.get("UPSTOX_ACCESS_TOKEN"))
