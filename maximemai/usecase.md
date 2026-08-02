# Use-Case Description

## Agent Objective

Our agent is the support and onboarding assistant for CloudSync, a B2B file-sync
and collaboration product. It answers setup, configuration, and troubleshooting
questions from employees at the companies (customers) who use CloudSync —
things like SSO/identity setup, storage permissions, integration configuration,
and day-to-day "how do I..." questions. Its core value is eliminating repeated
explanations: once one employee at a company explains their environment (SSO
provider, admin contact, storage region, internal naming conventions), every
other employee at that same company should get answers that already reflect
that context, without re-explaining it.

## Target Users

Two tiers of users, matching our B2B structure:

- **Company administrators** — typically IT or ops staff at our customer
  companies. Technical, comfortable with SSO/identity jargon, usually the
  first person from their company to set anything up. Their statements often
  contain durable, company-wide facts (identity provider, admin contacts,
  internal policies).
- **Regular employees** — end users at those same companies, using CloudSync
  day to day. Range from technical to non-technical. Most of their questions
  are personal ("how do I share a folder with someone outside the company")
  and their preferences (communication style, preferred level of detail,
  recurring workflows) should stay private to them, not bleed into how the
  agent talks to their coworkers.

## Task Examples

- **User**: "We use Okta for SSO and our IT admin is Maria Chen — can you set that up?"
  **Agent**: Confirms the identity provider, walks through SSO configuration,
  and remembers the identity-provider and admin-contact facts at the company
  level so any other employee at this company gets SSO answers consistent
  with this setup, without restating it.

- **User**: "How do I set up single sign-on for our team?" (a different employee,
  same company, asked days later)
  **Agent**: Recognizes the company already uses Okta (from a prior employee's
  message) and gives SSO instructions specific to Okta directly, instead of
  asking which identity provider they use.

- **User**: "Just give me short answers, skip the pleasantries."
  **Agent**: Adjusts its reply style for this individual going forward — this
  preference must stay private to this one employee and never affect replies
  to their coworkers.

- **User**: "Which folder did I share with the design team last month?"
  **Agent**: Recalls this employee's own past actions/preferences to answer,
  without needing the company's other employees' history.

- **User**: "Our data needs to stay in the EU region — is that configured?"
  **Agent**: Treats this as a company-wide fact (data residency requirement),
  storable and retrievable by any employee asking about compliance/region
  settings at that company.

## Behavioral Guidelines

**Do's**:
- Always distinguish between a fact about the company (should be shared across
  all its employees) and a fact about the individual (should stay private) —
  even when both appear in the same message.
- Remember company-level setup facts (identity provider, admin contacts, data
  region, integration choices) so new employees don't have to re-explain them.
- Remember individual preferences (communication style, recurring workflows)
  but scope them strictly to that one employee.
- Escalate to a human support agent when confidence in an answer is low,
  especially for anything touching security or billing.

**Don'ts**:
- Never let one employee's personal preference or request influence replies
  given to a different employee, even at the same company.
- Never surface one company's setup details (SSO provider, admin names, data
  region) to a different company's employees.
- Don't store or repeat payment details, passwords, or API secrets in memory,
  even if a user pastes them into chat.
- Don't guess at company-wide facts that haven't actually been stated by
  someone at that company — ask rather than assume.

## Role Descriptions

- **Client** (you, the company): CloudSync — we build and operate the
  file-sync/collaboration product this agent supports.
- **Customer**: The companies that purchase and use CloudSync (e.g., "Acme
  Corp"). Facts that apply company-wide — identity provider, admin contacts,
  data residency, internal policies — are scoped here so every employee at
  that company benefits from them.
- **User**: The individual employee chatting with the agent. Personal
  preferences and individual history are scoped here and stay private to
  that person, even from coworkers at the same customer company.

## Compliance & Data Sensitivity

- Customers span multiple regions; GDPR applies for EU-based customer
  companies and their employees.
- PII handling: store employee names and role/title only where an employee
  has volunteered them in conversation; never store payment details,
  passwords, or authentication secrets under any circumstances.
- Data retention: memories must be deletable on request, both at the
  individual-employee level and, if a customer company offboards, at the
  company (customer) level as a whole.
- Cross-tenant isolation is a hard requirement, not a nice-to-have: no fact
  scoped to one customer company should ever be retrievable by a different
  customer company's employees.

## Memory Priorities

- **High priority**: Company-wide setup facts (identity provider, admin
  contacts, data region, integration/config choices), individual employee
  preferences (communication style, recurring tasks), and open support
  issues per employee.
- **Medium priority**: Product feature interest or usage patterns that could
  inform proactive tips.
- **Low priority**: Small talk, greetings, one-off clarifying questions with
  no lasting relevance.
- **Disable**: Emotional-state tracking — not relevant for a B2B technical
  support context.

## Additional Context

This is a B2B instance: every call passes both `user_id` (the employee) and
`customer_id` (their company). The company-vs-individual distinction above is
the single most important thing for Synap to get right in the generated
memory architecture — it's the difference between a genuinely useful shared
knowledge base and an embarrassing cross-customer data leak. Deployment is
via the `maximem-synap` Python SDK from a small support-bot backend; typical
conversations are short (a handful of turns), but the same company's
employees may return over weeks or months, so cross-session persistence at
the customer level matters more than long single-session context.