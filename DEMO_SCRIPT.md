# 🎥 5-Minute Video Pitch & Demo Script
### *AI Finance Controller: Run the Books and the Cash Position*

**Target Video Length**: 4:30 – 5:00 minutes  
**Target Audience**: Hackathon Judges / Finance Ops Evaluators  
**Live UI Link**: `http://localhost:8000`

---

## ⏱️ Minute-by-Minute Video Breakdown

### 🎬 0:00 – 0:45 | Step 1: The Problem & "Why Now"
- **Screen**: Camera on you + [README Architecture Diagram](https://github.com/lokesh-8888/ai-finance-controller#-end-to-end-system-architecture).
- **Talking Points**:
  > *"Hi everyone! Welcome to our AI Finance Controller. In 2026, the financial operations consensus is clear: **verification capacity, not generation speed, is the bottleneck**."*  
  > *"When Stripe batches settle net of fees, bank statements reflect grouped deposits 2 days later, and ERP ledger entries drift, manual finance teams spend weeks reconciling by hand. A false-positive match is worse than an uncollected invoice."*  
  > *"Our core principle is simple: **Financial truth must remain deterministic and auditable; AI should investigate ambiguity and provide decision support, not invent financial facts.** Let's see it live in action!"*

---

### ⚡ 0:45 – 1:45 | Step 2: Executive Overview & The 4-Way Multi-Source Funnel
- **Screen**: Open browser at `http://localhost:8000` on the **Executive Overview** tab.
- **Actions**:
  1. Point out the **2-Row Bento Grid**:
     - **Records Processed**: 196 entities (Bank, Gateway, ERP, AP).
     - **Baseline Accuracy**: 80.00% (deterministic Stage 1 exact & Stage 2 subset-sum).
     - **Final Accuracy**: **100.00%** with **+20.0% AI Lift** and **0% Fraud False Positive Rate**.
     - **Critical Exceptions**: 2 quarantined P0 fraud items ($15,124.50).
     - **30-Day Projected Cash**: $324,500.00 with infinite runway.
  2. Point out the **4-Stage Reconciliation Funnel**:
     - Stage 1: $O(1)$ exact hash matcher (33 matches).
     - Stage 2: Combinatorial subset-sum solver for grouped payouts (15 matches).
     - Stage 3: AI Cognitive Reasoner for tax withholding, FX drift, and vendor aliases (10 resolved).
     - Stage 4: P0 Quarantine for unbooked wires and unexplained variances (2 quarantined).

---

### 🔍 1:45 – 2:45 | Step 3: 4-Way Reconciliation Stream & AI Forensic Reasoning
- **Screen**: Click on the **Reconciliation** tab (or **AI Investigation** tab).
- **Actions**:
  1. Filter by **"AI Resolved"**: Show `BNK-0046` and `BNK-0047`.
  2. Click **"Inspect"** on `BNK-0046`:
     - Show the slide-out forensic drawer.
     - Explain how the AI correctly identified the **EUR 1,200.00 invoice from 'AWS Cloud Dublin'** converted to USD at the verified FX rate without hallucinating.
  3. Filter by **"Exceptions"**: Show how duplicate charges (`BNK-0051`, `BNK-0053`) and missing payouts (`GTW-0040`) are neatly itemized.

---

### 🚨 2:45 – 3:45 | Step 4: Exception Intelligence & 1-Click Human Remediation
- **Screen**: Click on the **Exception Intelligence** tab.
- **Actions**:
  1. Highlight the **P0 CRITICAL Banner**:
     - Explain that **$15,000.00 unbooked wire (BNK-0055)** was received with no sales invoice. Emphasize: *"The system refused to guess or force a false match—it quarantined the fraud."*
  2. Click **"Remediate ⚡"** on the table row:
     - Execute **`Post GL Entry`** or **`File Dispute`**.
     - Show how it auto-generates a balanced double-entry voucher ($\sum \text{Debits} == \sum \text{Credits}$) and writes an immutable **SHA-256 hash-chained audit log**.

---

### 📈 3:45 – 4:30 | Step 5: Real-Time Cash Position & Forward Runway
- **Screen**: Click on the **Cash Position & Runway** tab.
- **Actions**:
  1. Show the 5 multi-tier cash cards:
     - Settled Bank Cash ($200,000) + In-Flight Gateway Liquidity ($85,250) $-$ Committed AP Bills ($36,495.50) = **Adjusted Net Cash ($248,754.50)**.
  2. Walk through the **30-Day Forward Cash Trajectory Chart** (modeling $T+2$ gateway payout latency and safety buffer line).
  3. Walk through the **Liquidity Waterfall Bridge**.

---

### 💬 4:30 – 5:00 | Step 6: Grounded Copilot & Closing
- **Screen**: Click on the **Grounded Copilot & Audit** tab.
- **Actions**:
  1. Click the prompt chip: *"What is our overall reconciliation match rate?"* or *"List all P0 critical fraud exceptions"*.
  2. Show how the Copilot answers instantly with exact data citations directly from the SQLite database.
  3. Click **"Audit Memo"** at the top right to demonstrate 1-click compliance export for CFOs.
  4. Conclude:
     > *"That is the AI Finance Controller: 81 tests passing, 71,250 records/second throughput, 100% verified accuracy, and zero false positives. Thank you!"*
