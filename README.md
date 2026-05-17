# TRACE.AI 🤖
### **Turn-based Response Analytics & Chat Engine**

TRACE.AI is a local, multi-turn AI chatbot platform built using **LLaMA 3** (via Ollama), **FastAPI**, **MongoDB**, and a modern web-based frontend interface. It features a built-in, analytics-ready feedback system to track response ratings, correctness, and response lengths.

---

## 🚀 Phase 1 Features

*   **FastAPI Backend Server:** Robust, asynchronous API handling.
*   **Local LLaMA 3 Integration:** Powered by Ollama for fully local, private LLM execution.
*   **Database Management:** MongoDB connection for chat history and session persistence.
*   **User Authentication:** Complete register and login functionality.
*   **Interactive Web UI:** Modern, themed frontend chatbot interface.
*   **Session-Based Chat Handling:** Keeps track of individual user conversations.
*   **Mandatory Feedback Panel:** Captures response ratings, correctness, and optimal length feedback.
*   **Analytics-Ready Storage:** Structured data collection prepared for future analysis using `pandas`.

---

## 🛠️ Tech Stack

*   **Backend:** Python, FastAPI, Uvicorn
*   **Database:** MongoDB
*   **LLM Orchestration:** Ollama (LLaMA 3)
*   **Frontend:** HTML5, CSS3, JavaScript
*   **Data Analysis:** pandas

---

## ⚙️ Environment Configuration

Before running the project, create a `.env` file in the root directory and add your MongoDB connection URI:

```env
MONGO_URI=mongodb://localhost:27017/trace_ai

```

---

## 🏃 Run Project Locally

Follow these steps to get your local environment up and running:

### 1. Install Dependencies

Clone the repository, navigate into the project directory, and install the required Python packages:

```bash
pip install -r requirements.txt

```

### 2. Start Ollama & LLaMA 3

Ensure you have [Ollama](https://ollama.com/) installed and running on your system, then pull/start the LLaMA 3 model:

```bash
ollama run llama3

```

### 3. Run the Backend Server

Launch the FastAPI development server with auto-reload enabled:

```bash
uvicorn backend.app:app --reload

```

### 4. Access the Application

Open your web browser and navigate to the local address:

```text
[http://127.0.0.1:8000](http://127.0.0.1:8000)

```
