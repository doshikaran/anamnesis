"""Initial schema — all tables, indexes, triggers.

Revision ID: 001
Revises:
Create Date: 2025-03-10

"""
from typing import Sequence, Union

from alembic import op

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    op.execute("""
    CREATE TABLE users (
        id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        email               TEXT NOT NULL UNIQUE,
        full_name           TEXT,
        avatar_url          TEXT,
        google_id           TEXT UNIQUE,
        microsoft_id        TEXT UNIQUE,
        auth_provider       TEXT NOT NULL DEFAULT 'google',
        password_hash       TEXT,
        timezone            TEXT NOT NULL DEFAULT 'UTC',
        briefing_time       TIME NOT NULL DEFAULT '08:00:00',
        briefing_enabled    BOOLEAN NOT NULL DEFAULT TRUE,
        nudge_max_per_day   INTEGER NOT NULL DEFAULT 3,
        language            TEXT NOT NULL DEFAULT 'en',
        onboarding_complete BOOLEAN NOT NULL DEFAULT FALSE,
        onboarding_step     TEXT DEFAULT 'connect_first_source',
        plan                TEXT NOT NULL DEFAULT 'free',
        plan_expires_at     TIMESTAMPTZ,
        stripe_customer_id  TEXT UNIQUE,
        stripe_sub_id       TEXT UNIQUE,
        encryption_key_id   TEXT,
        data_export_token   TEXT,
        delete_requested_at TIMESTAMPTZ,
        push_endpoint       TEXT,
        push_p256dh         TEXT,
        push_auth           TEXT,
        push_enabled        BOOLEAN DEFAULT FALSE,
        created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        last_active_at      TIMESTAMPTZ,
        deleted_at          TIMESTAMPTZ
    )
    """)
    op.execute("CREATE INDEX idx_users_email ON users(email)")
    op.execute("CREATE INDEX idx_users_google_id ON users(google_id)")
    op.execute("CREATE INDEX idx_users_microsoft_id ON users(microsoft_id)")
    op.execute("CREATE INDEX idx_users_plan ON users(plan)")
    op.execute("CREATE INDEX idx_users_deleted ON users(deleted_at) WHERE deleted_at IS NULL")

    op.execute("""
    CREATE TABLE connections (
        id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        user_id             UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        source_type         TEXT NOT NULL,
        access_token        TEXT,
        refresh_token       TEXT,
        token_expires_at    TIMESTAMPTZ,
        scopes              TEXT[],
        microsoft_tenant_id TEXT,
        slack_team_id       TEXT,
        slack_team_name     TEXT,
        slack_bot_token     TEXT,
        slack_user_token    TEXT,
        bridge_webhook_secret TEXT,
        bridge_last_seen_at TIMESTAMPTZ,
        notion_workspace_id TEXT,
        notion_workspace_name TEXT,
        status              TEXT NOT NULL DEFAULT 'active',
        last_synced_at      TIMESTAMPTZ,
        last_error          TEXT,
        error_count         INTEGER DEFAULT 0,
        sync_cursor         TEXT,
        sync_enabled        BOOLEAN DEFAULT TRUE,
        sync_from_date      DATE,
        sync_frequency_mins INTEGER DEFAULT 30,
        display_name        TEXT,
        created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """)
    op.execute("CREATE INDEX idx_connections_user ON connections(user_id)")
    op.execute("CREATE INDEX idx_connections_type ON connections(source_type)")
    op.execute("CREATE INDEX idx_connections_status ON connections(status)")
    op.execute("""
    CREATE UNIQUE INDEX idx_connections_user_source_type
        ON connections(user_id, source_type)
        WHERE source_type NOT IN ('gmail', 'outlook_mail')
    """)

    op.execute("""
    CREATE TABLE people (
        id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        user_id             UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        display_name        TEXT NOT NULL,
        first_name          TEXT,
        last_name           TEXT,
        canonical_email     TEXT,
        all_emails          TEXT[],
        phone_numbers       TEXT[],
        avatar_url          TEXT,
        relationship_type   TEXT NOT NULL DEFAULT 'contact',
        relationship_label  TEXT,
        importance_score    FLOAT DEFAULT 0.5,
        is_starred          BOOLEAN DEFAULT FALSE,
        last_contact_at     TIMESTAMPTZ,
        last_outbound_at    TIMESTAMPTZ,
        last_inbound_at     TIMESTAMPTZ,
        avg_response_days   FLOAT,
        contact_frequency   TEXT,
        sentiment_score     FLOAT,
        sentiment_trend     TEXT,
        sentiment_updated_at TIMESTAMPTZ,
        known_facts         JSONB DEFAULT '[]',
        life_events         JSONB DEFAULT '[]',
        open_topics         JSONB DEFAULT '[]',
        sources             TEXT[],
        external_ids        JSONB DEFAULT '{}',
        merged_from         UUID[],
        is_merged           BOOLEAN DEFAULT FALSE,
        embedding           vector(1536),
        created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        last_analyzed_at    TIMESTAMPTZ
    )
    """)
    op.execute("CREATE INDEX idx_people_user ON people(user_id)")
    op.execute("CREATE INDEX idx_people_email ON people(canonical_email)")
    op.execute("CREATE INDEX idx_people_type ON people(relationship_type)")
    op.execute("CREATE INDEX idx_people_importance ON people(importance_score DESC)")
    op.execute("CREATE INDEX idx_people_last_contact ON people(last_contact_at DESC)")
    op.execute("CREATE INDEX idx_people_starred ON people(user_id, is_starred) WHERE is_starred = TRUE")
    op.execute("""
    CREATE INDEX idx_people_embedding ON people
        USING hnsw (embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 64)
    """)
    op.execute("CREATE INDEX idx_people_name_trgm ON people USING gin(display_name gin_trgm_ops)")

    op.execute("""
    CREATE TABLE threads (
        id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        user_id             UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        connection_id       UUID REFERENCES connections(id) ON DELETE SET NULL,
        source_type         TEXT NOT NULL,
        external_thread_id  TEXT,
        subject             TEXT,
        participant_ids     UUID[],
        message_count       INTEGER DEFAULT 0,
        last_message_at     TIMESTAMPTZ,
        last_message_id     UUID,
        thread_summary      TEXT,
        status              TEXT DEFAULT 'active',
        sentiment_overall   FLOAT,
        created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """)
    op.execute("CREATE INDEX idx_threads_user ON threads(user_id)")
    op.execute("CREATE INDEX idx_threads_last_message ON threads(user_id, last_message_at DESC)")
    op.execute("""
    CREATE UNIQUE INDEX idx_threads_external
        ON threads(user_id, source_type, external_thread_id)
        WHERE external_thread_id IS NOT NULL
    """)

    op.execute("""
    CREATE TABLE messages (
        id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        user_id             UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        connection_id       UUID REFERENCES connections(id) ON DELETE SET NULL,
        source_type         TEXT NOT NULL,
        external_id         TEXT,
        thread_id           TEXT,
        db_thread_id        UUID REFERENCES threads(id) ON DELETE SET NULL,
        sender_person_id    UUID REFERENCES people(id) ON DELETE SET NULL,
        sender_raw          TEXT,
        recipient_person_ids UUID[],
        recipients_raw      TEXT[],
        direction           TEXT NOT NULL,
        subject             TEXT,
        body_raw            TEXT,
        body_clean          TEXT,
        body_summary        TEXT,
        message_type        TEXT NOT NULL DEFAULT 'text',
        audio_s3_key        TEXT,
        transcript          TEXT,
        sentiment_score     FLOAT,
        sentiment_label     TEXT,
        topics              TEXT[],
        entities_mentioned  JSONB DEFAULT '[]',
        has_commitment      BOOLEAN DEFAULT FALSE,
        has_question        BOOLEAN DEFAULT FALSE,
        importance_score    FLOAT DEFAULT 0.0,
        content_hash        TEXT,
        embedding           vector(1536),
        sent_at             TIMESTAMPTZ NOT NULL,
        received_at         TIMESTAMPTZ,
        created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        deleted_at          TIMESTAMPTZ
    )
    """)
    op.execute("CREATE INDEX idx_messages_user ON messages(user_id)")
    op.execute("CREATE INDEX idx_messages_source ON messages(source_type)")
    op.execute("CREATE INDEX idx_messages_thread ON messages(db_thread_id)")
    op.execute("CREATE INDEX idx_messages_sender ON messages(sender_person_id)")
    op.execute("CREATE INDEX idx_messages_sent_at ON messages(user_id, sent_at DESC)")
    op.execute("CREATE INDEX idx_messages_commitment ON messages(user_id, has_commitment) WHERE has_commitment = TRUE")
    op.execute("""
    CREATE UNIQUE INDEX idx_messages_dedup
        ON messages(user_id, source_type, external_id)
        WHERE external_id IS NOT NULL
    """)
    op.execute("CREATE INDEX idx_messages_hash ON messages(user_id, content_hash) WHERE content_hash IS NOT NULL")
    op.execute("""
    CREATE INDEX idx_messages_embedding ON messages
        USING hnsw (embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 64)
    """)

    op.execute("""
    CREATE TABLE commitments (
        id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        user_id             UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        description         TEXT NOT NULL,
        raw_text            TEXT,
        commitment_type     TEXT NOT NULL DEFAULT 'promise',
        direction           TEXT NOT NULL DEFAULT 'outbound',
        person_id           UUID REFERENCES people(id) ON DELETE SET NULL,
        person_name_raw     TEXT,
        source_message_id   UUID REFERENCES messages(id) ON DELETE SET NULL,
        source_thread_id    UUID REFERENCES threads(id) ON DELETE SET NULL,
        source_type         TEXT,
        deadline_at         TIMESTAMPTZ,
        deadline_raw        TEXT,
        deadline_type       TEXT,
        deadline_confidence FLOAT,
        status              TEXT NOT NULL DEFAULT 'open',
        completed_at        TIMESTAMPTZ,
        dismissed_at        TIMESTAMPTZ,
        dismissed_reason    TEXT,
        snoozed_until       TIMESTAMPTZ,
        extraction_confidence FLOAT,
        is_verified         BOOLEAN DEFAULT FALSE,
        urgency_score       FLOAT DEFAULT 0.5,
        priority            TEXT DEFAULT 'medium',
        nudge_count         INTEGER DEFAULT 0,
        last_nudged_at      TIMESTAMPTZ,
        next_nudge_at       TIMESTAMPTZ,
        created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """)
    op.execute("CREATE INDEX idx_commitments_user ON commitments(user_id)")
    op.execute("CREATE INDEX idx_commitments_status ON commitments(user_id, status)")
    op.execute("CREATE INDEX idx_commitments_person ON commitments(person_id)")
    op.execute("""
    CREATE INDEX idx_commitments_deadline
        ON commitments(user_id, deadline_at ASC)
        WHERE status = 'open' AND deadline_at IS NOT NULL
    """)
    op.execute("CREATE INDEX idx_commitments_urgency ON commitments(user_id, urgency_score DESC) WHERE status = 'open'")
    op.execute("""
    CREATE INDEX idx_commitments_next_nudge
        ON commitments(next_nudge_at ASC)
        WHERE status = 'open' AND next_nudge_at IS NOT NULL
    """)

    op.execute("""
    CREATE TABLE relationship_events (
        id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        user_id             UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        person_id           UUID NOT NULL REFERENCES people(id) ON DELETE CASCADE,
        source_message_id   UUID REFERENCES messages(id) ON DELETE SET NULL,
        event_type          TEXT NOT NULL,
        description         TEXT NOT NULL,
        event_date          DATE,
        event_date_approx   BOOLEAN DEFAULT FALSE,
        confidence          FLOAT DEFAULT 0.9,
        raw_text            TEXT,
        requires_followup   BOOLEAN DEFAULT FALSE,
        followup_done       BOOLEAN DEFAULT FALSE,
        followup_due_at     DATE,
        created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """)
    op.execute("CREATE INDEX idx_rel_events_user ON relationship_events(user_id)")
    op.execute("CREATE INDEX idx_rel_events_person ON relationship_events(person_id)")
    op.execute("CREATE INDEX idx_rel_events_type ON relationship_events(event_type)")
    op.execute("CREATE INDEX idx_rel_events_date ON relationship_events(event_date DESC)")

    op.execute("""
    CREATE TABLE insights (
        id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        user_id             UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        insight_type        TEXT NOT NULL,
        title               TEXT NOT NULL,
        body                TEXT NOT NULL,
        summary             TEXT,
        person_ids          UUID[],
        commitment_ids      UUID[],
        message_ids         UUID[],
        importance_score    FLOAT DEFAULT 0.5,
        is_actionable       BOOLEAN DEFAULT FALSE,
        suggested_action    TEXT,
        status              TEXT DEFAULT 'unread',
        read_at             TIMESTAMPTZ,
        acted_at            TIMESTAMPTZ,
        dismissed_at        TIMESTAMPTZ,
        user_feedback       TEXT,
        scheduled_for       TIMESTAMPTZ,
        sent_at             TIMESTAMPTZ,
        expires_at          TIMESTAMPTZ,
        model_used          TEXT,
        prompt_version      TEXT,
        generation_cost_usd FLOAT,
        created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """)
    op.execute("CREATE INDEX idx_insights_user ON insights(user_id)")
    op.execute("CREATE INDEX idx_insights_type ON insights(insight_type)")
    op.execute("CREATE INDEX idx_insights_status ON insights(user_id, status)")
    op.execute("CREATE INDEX idx_insights_scheduled ON insights(scheduled_for ASC) WHERE sent_at IS NULL")
    op.execute("CREATE INDEX idx_insights_importance ON insights(user_id, importance_score DESC) WHERE status = 'unread'")

    op.execute("""
    CREATE TABLE notifications (
        id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        user_id             UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        insight_id          UUID REFERENCES insights(id) ON DELETE SET NULL,
        commitment_id       UUID REFERENCES commitments(id) ON DELETE SET NULL,
        channel             TEXT NOT NULL,
        title               TEXT NOT NULL,
        body                TEXT NOT NULL,
        action_url          TEXT,
        status              TEXT NOT NULL DEFAULT 'pending',
        sent_at             TIMESTAMPTZ,
        delivered_at        TIMESTAMPTZ,
        clicked_at          TIMESTAMPTZ,
        failed_reason       TEXT,
        notification_key    TEXT,
        created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """)
    op.execute("CREATE INDEX idx_notifications_user ON notifications(user_id)")
    op.execute("CREATE INDEX idx_notifications_status ON notifications(status)")
    op.execute("CREATE INDEX idx_notifications_pending ON notifications(created_at ASC) WHERE status = 'pending'")
    op.execute("CREATE UNIQUE INDEX idx_notifications_key ON notifications(notification_key) WHERE notification_key IS NOT NULL")

    op.execute("""
    CREATE TABLE queries (
        id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        user_id             UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        input_text          TEXT NOT NULL,
        input_type          TEXT DEFAULT 'text',
        audio_s3_key        TEXT,
        intent              TEXT,
        entities_resolved   JSONB,
        response_text       TEXT,
        response_type       TEXT,
        draft_content       TEXT,
        source_message_ids  UUID[],
        source_person_ids   UUID[],
        model_used          TEXT,
        tokens_used         INTEGER,
        cost_usd            FLOAT,
        latency_ms          INTEGER,
        was_helpful         BOOLEAN,
        feedback_text       TEXT,
        created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """)
    op.execute("CREATE INDEX idx_queries_user ON queries(user_id)")
    op.execute("CREATE INDEX idx_queries_created ON queries(user_id, created_at DESC)")

    op.execute("""
    CREATE TABLE ingestion_jobs (
        id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        user_id             UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        connection_id       UUID REFERENCES connections(id) ON DELETE CASCADE,
        job_type            TEXT NOT NULL,
        status              TEXT NOT NULL DEFAULT 'queued',
        total_items         INTEGER,
        processed_items     INTEGER DEFAULT 0,
        failed_items        INTEGER DEFAULT 0,
        progress_pct        FLOAT DEFAULT 0.0,
        queued_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        started_at          TIMESTAMPTZ,
        completed_at        TIMESTAMPTZ,
        duration_ms         INTEGER,
        items_created       INTEGER DEFAULT 0,
        items_updated       INTEGER DEFAULT 0,
        items_skipped       INTEGER DEFAULT 0,
        error_log           JSONB DEFAULT '[]',
        celery_task_id      TEXT,
        created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """)
    op.execute("CREATE INDEX idx_jobs_user ON ingestion_jobs(user_id)")
    op.execute("CREATE INDEX idx_jobs_status ON ingestion_jobs(status)")
    op.execute("CREATE INDEX idx_jobs_connection ON ingestion_jobs(connection_id)")

    op.execute("""
    CREATE TABLE privacy_settings (
        id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        user_id             UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE UNIQUE,
        excluded_person_ids UUID[] DEFAULT '{}',
        excluded_sources    TEXT[] DEFAULT '{}',
        excluded_emails     TEXT[] DEFAULT '{}',
        allow_sentiment     BOOLEAN DEFAULT TRUE,
        allow_pattern_detection BOOLEAN DEFAULT TRUE,
        allow_relationship_scoring BOOLEAN DEFAULT TRUE,
        message_retention_days INTEGER DEFAULT 365,
        delete_raw_after_analysis BOOLEAN DEFAULT FALSE,
        created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """)

    op.execute("""
    CREATE TABLE usage_events (
        id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        user_id             UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        event_type          TEXT NOT NULL,
        quantity            INTEGER DEFAULT 1,
        cost_usd            FLOAT DEFAULT 0.0,
        model_used          TEXT,
        tokens_input        INTEGER,
        tokens_output       INTEGER,
        tokens_cached       INTEGER,
        reference_id        UUID,
        reference_type      TEXT,
        created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """)
    op.execute("CREATE INDEX idx_usage_user ON usage_events(user_id)")
    op.execute("CREATE INDEX idx_usage_created ON usage_events(user_id, created_at DESC)")
    op.execute("CREATE INDEX idx_usage_type ON usage_events(event_type)")

    op.execute("""
    CREATE OR REPLACE FUNCTION update_updated_at()
    RETURNS TRIGGER AS $$
    BEGIN
        NEW.updated_at = NOW();
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql
    """)
    op.execute("CREATE TRIGGER users_updated_at BEFORE UPDATE ON users FOR EACH ROW EXECUTE FUNCTION update_updated_at()")
    op.execute("CREATE TRIGGER connections_updated_at BEFORE UPDATE ON connections FOR EACH ROW EXECUTE FUNCTION update_updated_at()")
    op.execute("CREATE TRIGGER people_updated_at BEFORE UPDATE ON people FOR EACH ROW EXECUTE FUNCTION update_updated_at()")
    op.execute("CREATE TRIGGER threads_updated_at BEFORE UPDATE ON threads FOR EACH ROW EXECUTE FUNCTION update_updated_at()")
    op.execute("CREATE TRIGGER commitments_updated_at BEFORE UPDATE ON commitments FOR EACH ROW EXECUTE FUNCTION update_updated_at()")
    op.execute("CREATE TRIGGER privacy_settings_updated_at BEFORE UPDATE ON privacy_settings FOR EACH ROW EXECUTE FUNCTION update_updated_at()")


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS privacy_settings_updated_at ON privacy_settings")
    op.execute("DROP TRIGGER IF EXISTS commitments_updated_at ON commitments")
    op.execute("DROP TRIGGER IF EXISTS threads_updated_at ON threads")
    op.execute("DROP TRIGGER IF EXISTS people_updated_at ON people")
    op.execute("DROP TRIGGER IF EXISTS connections_updated_at ON connections")
    op.execute("DROP TRIGGER IF EXISTS users_updated_at ON users")
    op.execute("DROP FUNCTION IF EXISTS update_updated_at()")

    op.execute("DROP TABLE IF EXISTS usage_events")
    op.execute("DROP TABLE IF EXISTS privacy_settings")
    op.execute("DROP TABLE IF EXISTS ingestion_jobs")
    op.execute("DROP TABLE IF EXISTS queries")
    op.execute("DROP TABLE IF EXISTS notifications")
    op.execute("DROP TABLE IF EXISTS insights")
    op.execute("DROP TABLE IF EXISTS relationship_events")
    op.execute("DROP TABLE IF EXISTS commitments")
    op.execute("DROP TABLE IF EXISTS messages")
    op.execute("DROP TABLE IF EXISTS threads")
    op.execute("DROP TABLE IF EXISTS people")
    op.execute("DROP TABLE IF EXISTS connections")
    op.execute("DROP TABLE IF EXISTS users")
