/* =====================================================================
   Phase 9 alert store (schema mon), OPTIONAL
   ---------------------------------------------------------------------
   Tables a live deployment would use to keep the weekly alerts and their
   lifecycle. Phase 9 only DESIGNS them: the back-test writes CSV files
   (reports/phase9/weekly_alerts.csv) and this script creates the empty
   tables so the design is checked against both engines. Nothing is
   deployed to production.

   mon.signal_rule          the selected rule per signal x entity type
   mon.alert                one row per alert (signal x entity x week);
                            alert_id = signal-entitytype-entity-week
   mon.alert_status_history one row per lifecycle change (NEW,
                            ACKNOWLEDGED, INVESTIGATING, ACTIONED,
                            MONITORING, RESOLVED, FALSE POSITIVE); a
                            FALSE POSITIVE or RESOLVED change needs a
                            reason. Management responses are entered by
                            people, never generated.
   ===================================================================== */

SET NOCOUNT ON;
-- Drop the child table first: alert_status_history references alert.
DROP TABLE IF EXISTS mon.alert_status_history;
DROP TABLE IF EXISTS mon.alert;
DROP TABLE IF EXISTS mon.signal_rule;
GO

CREATE TABLE mon.signal_rule (
    signal                   NVARCHAR(8)    NOT NULL,
    entity_type              NVARCHAR(20)   NOT NULL,
    rule_family              NVARCHAR(40)   NOT NULL,
    threshold                NVARCHAR(40)   NOT NULL,
    persistence_weeks        INT            NOT NULL,
    valid_from_week          INT            NOT NULL,   -- retail_week_key the rule applies from
    approved_by              NVARCHAR(100)  NULL,       -- empty until a person approves it
    CONSTRAINT pk_signal_rule PRIMARY KEY (signal, entity_type, valid_from_week)
);
GO

CREATE TABLE mon.alert (
    alert_id                 NVARCHAR(60)   NOT NULL,
    alert_date               DATE           NOT NULL,
    retail_week_key          INT            NOT NULL,
    signal                   NVARCHAR(8)    NOT NULL,
    entity_type              NVARCHAR(20)   NOT NULL,
    entity_id                NVARCHAR(100)  NOT NULL,
    metric                   NVARCHAR(200)  NOT NULL,
    actual_value             DECIMAL(18,6)  NULL,
    baseline_value           DECIMAL(18,6)  NULL,
    variance                 DECIMAL(18,6)  NULL,
    variance_pct             DECIMAL(18,6)  NULL,
    z_score                  DECIMAL(18,6)  NULL,
    rule_text                NVARCHAR(200)  NOT NULL,
    severity                 NVARCHAR(10)   NOT NULL,   -- WATCH, WARNING, CRITICAL
    severity_reason          NVARCHAR(400)  NULL,
    persistence_weeks        INT            NOT NULL,
    alert_episode_id         NVARCHAR(60)   NOT NULL,
    estimated_exposure       DECIMAL(14,2)  NULL,       -- monitoring ESTIMATE; never summed across signals
    dq_status                NVARCHAR(10)   NOT NULL,
    dq_hold                  BIT            NOT NULL,
    evidence_level           NVARCHAR(60)   NOT NULL,
    cause_status             NVARCHAR(40)   NOT NULL,   -- always 'Not established' when created
    message                  NVARCHAR(600)  NOT NULL,
    proposed_owner           NVARCHAR(100)  NOT NULL,
    status                   NVARCHAR(20)   NOT NULL,   -- current lifecycle status
    owner                    NVARCHAR(100)  NULL,       -- a named person, entered by people
    created_at               DATETIME2(0)   NOT NULL,
    acknowledged_at          DATETIME2(0)   NULL,
    resolved_at              DATETIME2(0)   NULL,
    resolution_reason        NVARCHAR(400)  NULL,
    notes                    NVARCHAR(1000) NULL,
    CONSTRAINT pk_alert PRIMARY KEY (alert_id),
    CONSTRAINT ck_alert_severity CHECK (severity IN (N'WATCH', N'WARNING', N'CRITICAL')),
    CONSTRAINT ck_alert_status CHECK (status IN (N'NEW', N'ACKNOWLEDGED', N'INVESTIGATING', N'ACTIONED',
                                                  N'MONITORING', N'RESOLVED', N'FALSE POSITIVE'))
);
GO

CREATE TABLE mon.alert_status_history (
    alert_id                 NVARCHAR(60)   NOT NULL,
    changed_at               DATETIME2(0)   NOT NULL,
    old_status               NVARCHAR(20)   NULL,
    new_status               NVARCHAR(20)   NOT NULL,
    changed_by               NVARCHAR(100)  NOT NULL,
    reason                   NVARCHAR(400)  NULL,       -- required for RESOLVED and FALSE POSITIVE
    CONSTRAINT pk_alert_status_history PRIMARY KEY (alert_id, changed_at),
    CONSTRAINT fk_alert_status_history_alert FOREIGN KEY (alert_id) REFERENCES mon.alert (alert_id)
);
GO
