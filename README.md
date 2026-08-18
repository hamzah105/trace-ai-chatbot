# TRACE.AI
## ~Turn-based Response Analytics & Chat Engine

TRACE.AI is a local multi-turn AI chatbot platform built using **LLaMA 3 via Ollama**, **FastAPI**, **MongoDB**, and a web-based frontend interface. The system allows users to register, login, interact with a local AI chatbot, and submit mandatory feedback after each response.

The project is developed for the **CS619 Final Year Project**. The marked Phase 1 foundation is preserved, and this version completes only **Phase 2 (FR6-FR13)**. Phase 3 analytics are intentionally not implemented.

---

## Project Domain

**Artificial Intelligence / Natural Language Processing / Conversational AI**

---

## Phase 1 Implemented Features

The following Phase 1 requirements have been implemented:

### 1. System Initialization

- FastAPI backend server initialization
- MongoDB database connection setup
- Ollama-based LLaMA 3 local model integration
- Analytics module placeholder using pandas

### 2. Frontend Chat Interface

- Register page
- Login page
- Modern chatbot interface
- User input and AI response display
- Mandatory feedback panel:
  - Rating: 1 to 4
  - Correctness: Correct / Partial / Incorrect
  - Length type: Short / To the Point / Lengthy

### 3. Backend Server Development

- FastAPI backend implementation
- User registration and login routes
- Session ID generation and management
- Message routing to local LLaMA 3 model
- Chat history and feedback storage in MongoDB

### 4. LLaMA 3 Model Integration

- Local AI response generation using Ollama
- Backend communicates with Ollama API
- LLaMA 3 is used as the chatbot engine

### 5. Service Connectivity

The project connects:

```text
Frontend UI
    ↓
FastAPI Backend API
    ↓
Ollama / LLaMA 3 Model
    ↓
MongoDB Database
    ↓
Analytics-Ready Data Storage
```

---

## Phase 2 Implemented Features (FR6-FR13)

| Requirement | Implementation |
|---|---|
| FR6 - User Authentication | Existing local register/login is preserved. Google OAuth uses signed CSRF state, creates or retrieves MongoDB profiles, and returns safe profile data through a short-lived HttpOnly login handoff. |
| FR7 - Session Management | Dedicated `sessions` collection and create, retrieve, list, and end routes with user ownership checks. |
| FR8 - Multi-Turn Chat | Full history is stored while only the latest eight interactions from the same user/session are sent as context. |
| FR9 - LLaMA 3 Responses | Local Ollama/LLaMA 3 remains the engine, with configurable model/URL, HTTP checks, empty-response checks, and explicit timeouts. |
| FR10 - Response Time | Every saved interaction has request start, response end, and elapsed seconds; the Phase 1 `response_time` alias remains. |
| FR11 - Real-Time Storage | Every interaction stores user/session IDs, both messages, timestamps, a rule-based topic label, and feedback state. |
| FR12 - Mandatory Feedback | Rating, correctness, and length values are validated by the backend and linked to the correct interaction/user/session. |
| FR13 - Input Control | The UI locks after a response; the backend also returns HTTP 409 until the latest response receives feedback. |

Allowed stored topic labels are Machine Learning, Deep Learning, Healthcare AI, Power Systems, E-commerce AI, and General. These labels prepare data for later work; no topic analytics are calculated in Phase 2.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python, FastAPI, Uvicorn |
| AI Model Runtime | Ollama |
| Local LLM | LLaMA 3 |
| Database | MongoDB |
| Frontend | HTML5, CSS3, JavaScript |
| Analytics Placeholder | pandas |
| Development Environment | VS Code |

---

## Project Folder Structure
**(please note that project structure is in premature phase, hence some folders are empty those would be developed in future phases)**
```text
|   .env
|   .gitignore
|   README.md
|   requirements.txt
|   sample.env
|   TREE.txt
|
+---backend
|   |   app.py
|   |   main.py
|   |
|   +---analytics
|   |   |   metrics.py
|   |   |
|   |
|   +---database
|   |   |   database.py
|   |   |
|   |
|   +---routes
|   |   |   auth.py
|   |   |   chat.py
|   |   |   feedback.py
|   |   |   sessions.py
|   |
|   +---services
|   |   |   chat_storage.py
|   |   |   ollama_service.py
|   |   |   session_service.py
|   |   |   topic_service.py
|
+---config
|   |   database.py
|
+---data
+---frontend
|       background.js
|       index.html
|       login.html
|       night.gif
|       register.html
|       style.css
|       yin.png
|
+---models
+---tests
|       test_google_oauth.py
|       test_phase2.py
|
\---utils
```

---

## Prerequisites

Before running the project, make sure the following software is installed.

### 1. Python

Recommended version:

```text
Python 3.10 or above
```

### 2. MongoDB Community Server

MongoDB must be installed and running locally.

Default local MongoDB URI:

```text
mongodb://localhost:27017/
```

### 3. Ollama

Install Ollama from the official website:

```text
https://ollama.com/
```

After installation, verify Ollama:

### 4. LLaMA 3 Model

Pull or run LLaMA 3 using Ollama:

```bash
ollama run llama3
```

This command downloads the model if it is not already installed.

---

## Environment Configuration

Create a `.env` file in the root directory of the project.

Example:

```text
TRACE/
├── .env
```
A `sample.env` file may also be included for reference:

```env
MONGO_URI=mongodb://localhost:27017/
MONGO_DB_NAME=trace_ai
OLLAMA_URL=http://localhost:11434/api/generate
OLLAMA_MODEL=llama3
OLLAMA_TIMEOUT_SECONDS=300

# Optional. Leave the client values blank to keep Google login disabled.
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
GOOGLE_REDIRECT_URI=http://127.0.0.1:8000/auth/google/callback
GOOGLE_OAUTH_STATE_SECRET=change-this-local-dev-secret
```

For Google OAuth, create a Google Cloud OAuth 2.0 Web application and register
`http://127.0.0.1:8000/auth/google/callback` as an authorized redirect URI. Copy
the client ID and client secret into `.env`, replace the sample state secret with
a long random value, and restart FastAPI. Credentials and secrets must never be
placed in frontend files or committed to source control.

## Installation Guide

Open terminal or VS Code terminal inside the root project folder:

```bash
cd TRACE
```

Install the pinned project dependencies:

```bash
py -m pip install -r requirements.txt
```

This will install the required dependencies such as:

- fastapi
- uvicorn
- pymongo
- python-dotenv
- pandas
- requests
- pydantic etc
---

## How to Run the Project

Follow these steps in order.

### Step 1: Start MongoDB

Make sure MongoDB service is running.

---

### Step 2: Start Ollama / LLaMA 3

Open a terminal and run:

```bash
ollama run llama3
```

Keep Ollama available in the background.

If the model is already installed, this will start the model session.

---

### Step 3: Run FastAPI Backend

Open another terminal inside the project folder and run:

```bash
uvicorn backend.app:app --reload
```

Expected output:

```text
Uvicorn running on http://127.0.0.1:8000
Application startup complete.
MongoDB Connected Successfully.
```

---

### Step 4: Open the Application

Open your browser and visit:

```text
http://127.0.0.1:8000
```

The system should open the login page.

---

## Application Flow

```text
User opens TRACE.AI
    ↓
User registers or logs in
    ↓
Chat interface opens
    ↓
User sends message
    ↓
FastAPI sends prompt to Ollama / LLaMA 3
    ↓
LLaMA 3 generates response
    ↓
Response is displayed in frontend
    ↓
User submits mandatory feedback
    ↓
Chat and feedback data are stored in MongoDB
```

---

## FastAPI API Documentation

FastAPI automatically provides API documentation.

After running the backend, open:

```text
http://127.0.0.1:8000/docs
```

Available main routes include:

| Endpoint | Method | Purpose |
|---|---|---|
| `/register` | POST | Register new user |
| `/login` | POST | Login existing user |
| `/chat` | POST | Send message to LLaMA 3 |
| `/feedback` | POST | Submit response feedback |
| `/users/{user_id}` | GET | Retrieve a safe user profile |
| `/auth/google/status` | GET | Report whether optional Google OAuth is configured |
| `/auth/google/login` | GET | Start optional Google OAuth login |
| `/auth/google/callback` | GET | Validate Google OAuth and create/retrieve the user profile |
| `/auth/google/session` | GET | Consume the short-lived login handoff and return the safe profile |
| `/sessions/create` | POST | Create a user-owned chat session |
| `/sessions/{session_id}` | GET | Retrieve a session and pending-feedback state |
| `/sessions/user/{user_id}` | GET | List a user's sessions |
| `/sessions/{session_id}/end` | POST | End a user-owned session |
| `/health` | GET | Check backend status |

---

## MongoDB Collections

The project stores data in MongoDB.

Main database:

```text
trace_ai
```

Expected collections:

### users

Stores registered user data:

```json
{
  "name": "User Name",
  "email": "user@example.com",
  "password": "bcrypt hash for local users",
  "auth_provider": "local",
  "created_at": "date-time",
  "last_login": "date-time"
}
```

Google-created or Google-linked profiles additionally store:

```json
{
  "name": "Google User",
  "email": "user@gmail.com",
  "auth_provider": "google",
  "google_sub": "google-account-identifier",
  "picture": "https://optional-profile-image",
  "created_at": "date-time",
  "last_login": "date-time"
}
```

### sessions

Stores independent user conversation state:

```json
{
  "session_id": "unique-session-id",
  "user_id": "user-id",
  "created_at": "date-time",
  "updated_at": "date-time",
  "status": "active",
  "message_count": 2,
  "summary": "",
  "topics": ["Deep Learning", "Healthcare AI"]
}
```

### chat_history

Stores chat messages, model responses, sessions, response time, and feedback:

```json
{
  "session_id": "unique-session-id",
  "user_id": "user-id",
  "user_message": "User question",
  "llama_response": "AI response",
  "timestamp": "date-time",
  "request_start_time": "date-time",
  "response_end_time": "date-time",
  "response_time_seconds": 12.5,
  "response_time": 12.5,
  "topic_label": "Machine Learning",
  "feedback": {
    "rating": 4,
    "correctness": "Correct",
    "length_type": "To the Point",
    "submitted": true,
    "submitted_at": "date-time"
  }
}
```

---

## Phase 1 Testing Checklist

Before submission, test the following:

| Test | Expected Result |
|---|---|
| Open `http://127.0.0.1:8000` | Login page opens |
| Register new user | User saved in MongoDB |
| Login with registered user | Redirects to chatbot page |
| Send message | LLaMA 3 response appears |
| Submit feedback | Feedback saved in MongoDB |
| Ask follow-up question | Session context is maintained |
| Open `/docs` | FastAPI API documentation appears |
| Check MongoDB Compass | `users` and `chat_history` collections contain data |

## Phase 2 Testing Checklist

Run the automated checks with:

```bash
py -m unittest discover -s tests -v
```

The checklist covers Google OAuth state and callback handling, local login compatibility, allowed topic labels, feedback validation, required chat storage fields, session history and ownership, the pending-feedback backend guard, and Ollama timeout handling. For a live integration check, also verify that two different-topic prompts in one session update `message_count` and `topics`, and that a chat request before feedback returns HTTP 409.

---

## Common Issues and Fixes (Just incase you face any issues)

### 1. MongoDB connection failed

Error may look like:

```text
No connection could be made because the target machine actively refused it
```

Fix:

- Make sure MongoDB Community Server is installed
- Start MongoDB service from `services.msc`
- Confirm MongoDB Compass connects to:

```text
mongodb://localhost:27017
```

---

### 2. Ollama connection error

If the chatbot does not respond, make sure Ollama is running:

```bash
ollama run llama3
```

Also confirm that Ollama API is available at:

```text
http://localhost:11434
```

---

### 3. `/chat` shows Method Not Allowed in browser

This is normal if `/chat` is opened directly in the browser.

`/chat` is a POST API route, not a normal webpage.

Use the frontend chat interface or FastAPI docs:

```text
http://127.0.0.1:8000/docs
```

---

### 4. Login succeeds but page does not redirect

Clear browser local storage and try again.

In browser console:

```javascript
localStorage.clear()
```

Then refresh and login again.

---

### 5. Feedback panel does not appear

Check that `/chat` returns an `interaction_id`.

You can test from:

```text
http://127.0.0.1:8000/docs
```

The `/chat` response should contain:

```json
{
  "interaction_id": "...",
  "session_id": "...",
  "user_message": "...",
  "llama_response": "...",
  "response_time": 0
}
```

---

### 6. Response is slow

This is expected on older CPUs or systems with limited RAM.

Possible improvements:

- Use shorter response length in Ollama options
- Use a smaller model
- Close unnecessary background applications
- Keep only the required services running

---

## Known Limitations

- Token-by-token response streaming is not implemented; Phase 2 uses normal request-response generation.
- Google OAuth requires a locally configured Google Cloud OAuth client and the exact documented callback URL.
- Frontend login state is stored in `localStorage` for this university demonstration.
- Response speed depends on the local computer, the selected Ollama model, and available memory.
- The analytics dashboard, charts, reports, and FR14-FR22 belong to Phase 3 and are not included.

---

## Phase 2 Scope Boundary

This version completes FR6 through FR13 while preserving the submitted Phase 1 application. Google OAuth automatically remains disabled when credentials are absent, and local login remains available. To enable Google OAuth, copy `sample.env` to `.env`, fill the Google variables, register the documented callback URL in Google Cloud, and restart FastAPI.

Phase 3 was not implemented. There is no analytics dashboard, analytics table, graph, admin analytics page, session analytics report, or FR14-FR22 implementation in this version.

---

## Supervisor

**Supervisor:** Miss Neelam Alam<br>
**Course:** CS619 Final Year Project

---

## Developer

**Student:** M Hamzah Shoaib
**Student ID:** BC230200900<br>
**Project:** TRACE.AI - Multi-Turn AI Chatbot with LLaMA 3

---
## Note form the developer
*"I have added user experience features inspired by different AI projects such as openclaw, which includes a rotating quotes bar that periodically displays informational and lightly sarcastic TRACE.AI related messages.
In future phases, I plan to implement an animated responsive character that reacts according to the conversation mood, making the chatbot more interactive and engaging."*
