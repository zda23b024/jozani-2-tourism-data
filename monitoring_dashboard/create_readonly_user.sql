-- Optional production setup for a dashboard-only PostgreSQL user.
-- Replace the password before running this manually as a database administrator.

CREATE ROLE jozani_dashboard_reader LOGIN PASSWORD 'change_me';

GRANT CONNECT ON DATABASE zanzibar_booking_data TO jozani_dashboard_reader;
GRANT USAGE ON SCHEMA public TO jozani_dashboard_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO jozani_dashboard_reader;
GRANT SELECT ON ALL SEQUENCES IN SCHEMA public TO jozani_dashboard_reader;

ALTER DEFAULT PRIVILEGES IN SCHEMA public
GRANT SELECT ON TABLES TO jozani_dashboard_reader;
