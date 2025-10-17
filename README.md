![Python](https://img.shields.io/badge/python-3.10%2B-blue?logo=python)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688?logo=fastapi)
![SerpAPI](https://img.shields.io/badge/SerpAPI-Integration-orange)
![Made with ❤️ in Detroit](https://img.shields.io/badge/Made%20with%20%E2%9D%A4%EF%B8%8F-in%20Detroit-red)

# 🏙️ FUNDR — AI-Powered Local Business Insights

> **FUNDR** helps banks, investors, and cities discover and fund thriving **small businesses** using real-world data from Google Local and AI-driven analytics.

Built with **FastAPI**, **SerpAPI**, and **ChatGPT**, FUNDR transforms raw Google Maps data into actionable _leaderboards, insights, and impact scores_ — highlighting the local businesses most deserving of funding.

---

## 🚀 Key Features

- 🔍 **Discover Local Businesses**
  - Search by city and category using Google Local data.
- 🧮 **FUNDR Score (0–100)**
  - **Quality** – Ratings + Review Volume
  - **Consistency** – Recency + Rating Trend
  - **Community** – Positive Sentiment (clean, kind, inclusive, affordable)
  - **Ops Fit** – Operational completeness (hours, phone, website)
- 🏆 **Leaderboard Mode**
  - Ranks top businesses per city and category.
- ⚡ **Quota-Efficient Design**
  - Only **7 SerpAPI calls** per full leaderboard (1 discovery + 3×[details + reviews]).
- 💬 **AI Insights**
  - Generates “Why Fund,” “Top Praise,” and “Top Fix” summaries per business.

---

## 🧩 Architecture Overview

```text
User → FUNDR FastAPI → SerpAPI (Google Local + Reviews)
                          ↓
             Scoring Engine (Quality, Consistency, Community, OpsFit)
                          ↓
                 Cache + Leaderboard → JSON / OpenAPI / Custom GPT
```

## 🛠️ Tech Stack

```
Layer Technology
Framework FastAPI (Python)
Data Source SerpAPI (Google Local + Reviews)
AI Integration ChatGPT / Custom GPT Action
Caching In-memory TTL (6 hours)
Scoring FUNDR algorithm (Quality • Consistency • Community • Ops Fit)
```

## 🔗 API Endpoints

| Endpoint               | Method | Description                                       |
| ---------------------- | ------ | ------------------------------------------------- |
| `/`                    | GET    | API root information                              |
| `/discover`            | GET    | Discover small businesses by city and category    |
| `/business/{place_id}` | GET    | Retrieve detailed info + reviews for one business |
| `/leaderboard`         | GET    | Get ranked businesses with FUNDR scores           |
| `/score/recompute`     | POST   | Recompute scores for all cached businesses        |

## 🧮 Example Usage

### Request

```
curl "http://127.0.0.1:8000/leaderboard?city=Detroit&category=coffee%20shops&limit=10"

```

### Response

```
{
  "city": "Detroit",
  "category": "coffee shops",
  "updated_at": "2025-10-17T19:00:00Z",
  "items": [
    {
      "place_id": "ChIJd8BlQ2BZwokRAFUEcm_qrcA",
      "name": "The Congregation Detroit",
      "fundr_score": 88.6,
      "subscores": {
        "quality": 0.92,
        "consistency": 0.88,
        "community": 0.75,
        "ops_fit": 0.9
      },
      "why_fund": "Strong praise for friendly service and community feel; opportunity to improve parking.",
      "badges": ["Community Favorite"]
    }
  ]
}

```

## 👤 Author

```
Jaylen Thomas
Software Engineer II @ JPMorgan Chase
Graduate Student (AI & Data Science)
Detroit-native • Climate-Tech • Community Impact Builder
```

## 🧠 Example “Why Fund” Insight

```
“Strong recent customer praise for friendly staff and community engagement; opportunity to improve wait times.”

⚡ Performance & Quota Protection

Each leaderboard request capped at 7 SerpAPI calls

Cached results live for 6 hours

Chain stores auto-filtered (200+ national brands)

Repeated queries = 0–1 API calls
```

## 🧩 Integrating with Custom GPT

```
FUNDR’s OpenAPI schema lets you build an interactive Custom GPT.

Example Prompt:

“Find the top small businesses in Atlanta worth funding this quarter.”

GPT Flow:

/discover → Fetch candidates

/leaderboard → Rank + explain “Why Fund”

Output → Contextual leaderboard and AI insights
```

## 🧭 Vision

```
FUNDR empowers cities, banks, and communities to invest in small businesses that uplift local economies — using data, not guesswork.
```
