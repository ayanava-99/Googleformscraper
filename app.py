import streamlit as st
import requests
import re
import json
from groq import Groq

# Configure the Streamlit page
st.set_page_config(page_title="Google Form Solver", page_icon="📝", layout="centered")

def scrape_google_form(url):
    """Scrapes questions and options from a Google Form URL."""
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
    except Exception as e:
        return None, f"Failed to fetch form: {str(e)}"
    
    html = response.text
    
    # Extract the JSON embedded in the form's HTML
    match = re.search(r'var FB_PUBLIC_LOAD_DATA_ = (\[.*?\]);\n', html, re.DOTALL)
    if not match:
         return None, "Could not find form data. Ensure the form is public and the link is correct."
         
    try:
        data = json.loads(match.group(1))
        # Questions are typically found in data[1][1]
        questions_data = data[1][1]
        parsed_questions = []
        
        for q in questions_data:
            if not isinstance(q, list) or len(q) < 2:
                continue
                
            question_text = q[1]
            options = []
            
            # Check if there are options (multiple choice, checkboxes, etc.)
            if len(q) > 4 and q[4]:
                for opt_group in q[4]:
                    if isinstance(opt_group, list) and len(opt_group) > 1 and opt_group[1]:
                        for opt in opt_group[1]:
                            if isinstance(opt, list) and len(opt) > 0:
                                options.append(opt[0])
            
            # Only add if it has a question text
            if question_text:
                parsed_questions.append({
                    "question": str(question_text),
                    "options": [str(o) for o in options] if options else []
                })
                
        if not parsed_questions:
            return None, "No questions could be parsed from the form."
            
        return parsed_questions, None
        
    except Exception as e:
        return None, f"Error parsing form data: {str(e)}"


def get_groq_answers(api_key, questions):
    """Uses Groq API to answer the extracted questions."""
    try:
        client = Groq(api_key=api_key)
        
        prompt = "You are a helpful assistant. Please provide the correct answer for the following questions. Output ONLY the question and the correct answer. Format it clearly.\n\n"
        for i, q in enumerate(questions):
            prompt += f"Q{i+1}: {q['question']}\n"
            if q['options']:
                prompt += "Options:\n"
                for opt in q['options']:
                    prompt += f"- {opt}\n"
            prompt += "\n"
            
        response = client.chat.completions.create(
            model="llama3-70b-8192",  # Using Llama 3 70B, which is free and fast on Groq
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0
        )
        
        return response.choices[0].message.content, None
    except Exception as e:
        return None, f"Groq API Error: {str(e)}"


# UI Design
st.title("📝 Google Form Scraper & Solver")
st.markdown("""
This app takes a public Google Form URL, scrapes its questions, and uses the **free Groq API (Llama 3)** to provide the correct answers.
""")

# Retrieve API key from Streamlit secrets
GROQ_API_KEY = st.secrets.get("GROQ_API_KEY")

if not GROQ_API_KEY:
    st.error("Groq API Key not found in secrets.toml!")
    st.stop()

with st.container():
    form_url = st.text_input("Google Form URL")
    
    submit_button = st.button("Get Answers", type="primary")

if submit_button:
    if not form_url or not form_url.startswith("http"):
        st.error("Please enter a valid Google Form URL.")
    else:
        with st.status("Processing...", expanded=True) as status:
            st.write("Scraping Google Form...")
            questions, error = scrape_google_form(form_url)
            
            if error:
                status.update(label="Scraping Failed", state="error", expanded=True)
                st.error(error)
            else:
                st.write(f"✅ Found {len(questions)} questions.")
                st.write("Getting answers from Groq (Llama 3 70B)...")
                
                answers, api_error = get_groq_answers(GROQ_API_KEY, questions)
                
                if api_error:
                    status.update(label="API Request Failed", state="error", expanded=True)
                    st.error(api_error)
                else:
                    status.update(label="Completed!", state="complete", expanded=False)
                    st.success("Answers generated successfully!")
                    
                    st.subheader("Results")
                    st.markdown(answers)
