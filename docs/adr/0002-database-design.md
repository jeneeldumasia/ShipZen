# ADR 0002: Database Design

**Status:** ACCEPTED (Amended)
**Context:** We need a primary database to serve as the Source of Truth for desired state. 
**Decision:** We will use PostgreSQL as the primary relational database and source of truth instead of MongoDB. It offers efficient and fast querying for strictly relational data models and enforces robust schema validation. Build logs will be stored in S3, not PostgreSQL.
**Consequences:** 
- Allows strong schema validation, referential integrity, and ACID compliance.
- Replaces previous MongoDB implementation.
- System bootstrapping (such as Admin user creation) relies strictly on parameterized variables like `ADMIN_EMAILS` rather than hardcoded logic to prevent elevation of privilege vulnerabilities.
**Conflict Resolution Policy:** Any implementations using MongoDB or NoSQL for core state will be rejected.
