# JavDB Node Selector Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a five-node JavDB/DBO metadata selector with live probing and provider-aware poster search.

**Architecture:** A focused `app/metadata_api.py` module owns signing, search, image URL handling, and node probing. FastAPI exposes compatibility search plus node probe endpoints, while the existing settings page gains a responsive selection dialog.

**Tech Stack:** Python 3.10+, FastAPI, urllib, vanilla JavaScript, CSS, pytest.

---

### Task 1: Configuration contract

- [ ] Add failing tests for selected provider, selected URL, and redacted DBO key persistence.
- [ ] Add configuration fields and request payload fields.
- [ ] Run the focused configuration tests.

### Task 2: Metadata client

- [ ] Add failing tests for JavDB signatures, JavDB response validation, DBO headers, mirror fallback, and node probe output.
- [ ] Implement `app/metadata_api.py` with injected network helpers for deterministic tests.
- [ ] Run metadata client tests.

### Task 3: FastAPI routes

- [ ] Add failing route tests for provider-aware search, five-node listing, selection, and DBO validation.
- [ ] Replace the fixed DBO route implementation with the metadata client and add probe endpoints.
- [ ] Run route tests.

### Task 4: Settings UI

- [ ] Add static UI tests for the JavDB card, five-node dialog, responsive controls, and provider-specific DBO fields.
- [ ] Update `index.html`, `app.js`, and `styles.css` to match the supplied desktop references.
- [ ] Run static UI tests.

### Task 5: Verification and publication

- [ ] Run `git diff --check` and the complete pytest suite with the repository on `PYTHONPATH`.
- [ ] Start the application and verify desktop and mobile screenshots, modal interaction, and non-overlap.
- [ ] Build, smoke-test, and push the Docker image after all checks pass.
