import streamlit as st
import requests

st.set_page_config(page_title="AI Chatbot")

st.title("AI Chatbot")
st.write("Dockerized Streamlit + FastAPI + Groq")

user_input = st.text_input("Enter your message")

if st.button("Send"):

    if user_input:

        response = requests.post(
            "http://backend:8000/chat",
            json={
                "message": user_input
            }
        )

        result = response.json()

        st.write("### AI Response")
        st.write(result["response"])