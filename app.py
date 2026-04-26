import streamlit as st
import requests
import re
import json
import base64
import os
from groq import Groq
from playwright.sync_api import sync_playwright
import nest_asyncio

nest_asyncio.apply()

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
    try:
        data_str = html.split('var FB_PUBLIC_LOAD_DATA_ = ')[1].split(';</script>')[0]
        data = json.loads(data_str)
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
        
        prompt = "You are a helpful assistant. Please provide the correct answer for the following questions. Output the response so that each answer is directly below its corresponding question. Use the format:\n\n**Question:** [The Question]\n**Answer:** [The Answer]\n\n"
        for i, q in enumerate(questions):
            prompt += f"Q{i+1}: {q['question']}\n"
            if q['options']:
                prompt += "Options:\n"
                for opt in q['options']:
                    prompt += f"- {opt}\n"
            prompt += "\n"
            
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",  # Using Llama 3.3 70B, which is free and fast on Groq
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0
        )
        
        return response.choices[0].message.content, None
    except Exception as e:
        return None, f"Groq API Error: {str(e)}"

def scrape_ms_form_playwright(url):
    """Uses Playwright to navigate to MS Form, wait for user login, and capture screenshots."""
    try:
        user_data_dir = os.path.join(os.getcwd(), "playwright_user_data")
        os.makedirs(user_data_dir, exist_ok=True)
        
        with sync_playwright() as p:
            browser = p.chromium.launch_persistent_context(
                user_data_dir=user_data_dir,
                headless=False, # Must be visible for initial login
                args=["--start-maximized"]
            )
            page = browser.pages[0] if browser.pages else browser.new_page()
            page.goto(url)
            
            # Wait for the form to load. Allow up to 120 seconds in case the user needs to log in with 2FA.
            try:
                page.wait_for_selector('div.office-form-question, [data-automation-id="questionItem"], button:has-text("Submit")', timeout=120000)
            except Exception:
                pass # Timeout reached, continue anyway to capture whatever is visible
                
            # Wait a few seconds to ensure all images and dynamic content are fully rendered
            page.wait_for_timeout(3000)
            
            # Capture full page screenshot
            screenshot_bytes = page.screenshot(full_page=True)
            browser.close()
            
            return screenshot_bytes, None
    except Exception as e:
        return None, f"Playwright error: {str(e)}"

def get_groq_vision_answers(api_key, image_bytes):
    """Uses Groq Vision API to answer questions from an image."""
    try:
        client = Groq(api_key=api_key)
        base64_image = base64.b64encode(image_bytes).decode('utf-8')
        
        prompt = """You are a helpful assistant. Please look at the provided screenshot of a Microsoft Form. 
Extract all the questions and their options, and provide the correct answer for each. 
Use the format:

**Question:** [The Question Text]
**Answer:** [The Correct Option / Answer]

"""
        response = client.chat.completions.create(
            model="llama-3.2-90b-vision-preview",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/png;base64,{base64_image}"
                            }
                        }
                    ]
                }
            ],
            temperature=0.0
        )
        return response.choices[0].message.content, None
    except Exception as e:
        return None, f"Groq Vision API Error: {str(e)}"
# UI Design
st.title("📝 Form Scraper & Solver")
st.markdown("""
This app solves both **Google Forms** (via URL scraping) and **Microsoft Forms** (via Browser Automation & Vision AI).
""")

# Retrieve API key from Streamlit secrets
GROQ_API_KEY = st.secrets.get("GROQ_API_KEY")

if not GROQ_API_KEY:
    st.error("Groq API Key not found in secrets.toml!")
    st.stop()

tab1, tab2 = st.tabs(["Google Forms", "Microsoft Forms (Automated)"])

with tab1:
    st.header("Google Forms")
    with st.container():
        form_url = st.text_input("Google Form URL", key="gform_url")
        submit_button = st.button("Get Answers", type="primary", key="gform_submit")

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

with tab2:
    st.header("Microsoft Forms")
    st.info("⚠️ First time: A browser will open and pause to let you log into your institutional account. Your login session will be saved locally for future use.")
    with st.container():
        ms_form_url = st.text_input("Microsoft Form URL", key="msform_url")
        ms_submit = st.button("Automate & Solve", type="primary", key="msform_submit")
        
    if ms_submit:
        if not ms_form_url or not ms_form_url.startswith("http"):
            st.error("Please enter a valid Microsoft Form URL.")
        else:
            with st.status("Processing with Playwright & Vision AI...", expanded=True) as status:
                st.write("Launching browser to capture form. Please log in if prompted...")
                screenshot_bytes, error = scrape_ms_form_playwright(ms_form_url)
                
                if error:
                    status.update(label="Browser Automation Failed", state="error", expanded=True)
                    st.error(error)
                else:
                    st.write("✅ Form captured successfully. Displaying screenshot:")
                    st.image(screenshot_bytes, caption="Captured Form Screenshot")
                    
                    st.write("Sending to Groq Vision AI (Llama 3.2 90B) to read questions and solve...")
                    answers, api_error = get_groq_vision_answers(GROQ_API_KEY, screenshot_bytes)
                    
                    if api_error:
                        status.update(label="Vision API Failed", state="error", expanded=True)
                        st.error(api_error)
                    else:
                        status.update(label="Completed!", state="complete", expanded=False)
                        st.success("Answers generated successfully!")
                        st.subheader("Results")
                        st.markdown(answers)
