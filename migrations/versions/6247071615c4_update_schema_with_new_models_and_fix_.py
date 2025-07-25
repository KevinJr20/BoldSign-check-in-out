"""incremental update: add new tables and convert date types

Revision ID: 6247071615c4
Revises: 
Create Date: 2025-07-22 14:52:42.157265

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '6247071615c4'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # Check and create new tables only if they don't exist
    op.execute('CREATE TABLE IF NOT EXISTS verification_tokens ('
               'id INTEGER NOT NULL, '
               'user_id VARCHAR(50) NOT NULL, '
               'token VARCHAR(36) NOT NULL, '
               'expires_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, '
               'PRIMARY KEY (id), '
               'UNIQUE (token), '
               'FOREIGN KEY(user_id) REFERENCES users (username))')
    op.execute('CREATE TABLE IF NOT EXISTS audit_log ('
               'id INTEGER NOT NULL, '
               'employee_id TEXT NOT NULL, '
               'action TEXT NOT NULL, '
               'timestamp TIMESTAMP WITHOUT TIME ZONE NOT NULL, '
               'PRIMARY KEY (id), '
               'FOREIGN KEY(employee_id) REFERENCES employees (employee_id))')
    op.execute('CREATE TABLE IF NOT EXISTS bookings ('
               'id INTEGER NOT NULL, '
               'room_id TEXT NOT NULL, '
               'guest_id TEXT NOT NULL, '  # Changed to TEXT to match guests.guest_id
               'check_in_date TIMESTAMP WITHOUT TIME ZONE NOT NULL, '
               'check_out_date TIMESTAMP WITHOUT TIME ZONE NOT NULL, '
               'status TEXT NOT NULL DEFAULT \'pending\', '
               'PRIMARY KEY (id), '
               'FOREIGN KEY(room_id) REFERENCES rooms (room_id), '
               'FOREIGN KEY(guest_id) REFERENCES guests (guest_id))')

    # Update existing tables with new column types and defaults
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.alter_column('username',
            existing_type=sa.VARCHAR(length=50),
            type_=sa.Text(),
            existing_nullable=False)
        batch_op.alter_column('password_hash',
            existing_type=sa.VARCHAR(length=255),
            type_=sa.Text(),
            existing_nullable=False)
        batch_op.alter_column('role',
            existing_type=sa.VARCHAR(length=20),
            type_=sa.Text(),
            existing_nullable=False,
            existing_server_default='admin',
            server_default='admin')

    with op.batch_alter_table('employees', schema=None) as batch_op:
        batch_op.alter_column('employee_id',
            existing_type=sa.VARCHAR(length=50),
            type_=sa.Text(),
            existing_nullable=False)
        batch_op.alter_column('name',
            existing_type=sa.VARCHAR(length=100),
            type_=sa.Text(),
            existing_nullable=False)
        batch_op.alter_column('fingerprint_template',
            existing_type=postgresql.BYTEA(),
            type_=sa.Text(),
            existing_nullable=False)
        # Add or alter columns that might not exist
        batch_op.add_column(sa.Column('email', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('role', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('organization_id', sa.Text(), nullable=False))
        batch_op.create_foreign_key('employees_organization_id_fkey', 'users', ['organization_id'], ['username'])

    with op.batch_alter_table('attendance', schema=None) as batch_op:
        batch_op.alter_column('id',
            existing_type=sa.INTEGER(),
            type_=sa.Integer(),
            existing_nullable=False)
        batch_op.alter_column('employee_id',
            existing_type=sa.VARCHAR(length=50),
            type_=sa.Text(),
            existing_nullable=True,
            nullable=False)
        batch_op.alter_column('name',
            existing_type=sa.VARCHAR(length=100),
            type_=sa.Text(),
            existing_nullable=True)
        batch_op.alter_column('date',
            existing_type=sa.DATE(),
            type_=sa.DateTime(),
            existing_nullable=False,
            postgresql_using='date::timestamp')
        batch_op.alter_column('time_in',
            existing_type=postgresql.TIME(),
            type_=sa.DateTime(),
            existing_nullable=True,
            postgresql_using='CAST(date AS TIMESTAMP) + time_in')
        batch_op.alter_column('time_out',
            existing_type=postgresql.TIME(),
            type_=sa.DateTime(),
            existing_nullable=True,
            postgresql_using='CAST(date AS TIMESTAMP) + time_out')
        batch_op.alter_column('timestamp',
            existing_type=postgresql.TIMESTAMP(timezone=True),
            type_=sa.DateTime(),
            existing_nullable=True)
        batch_op.alter_column('fingerprint',
            existing_type=postgresql.BYTEA(),
            type_=sa.Text(),
            existing_nullable=True)

    with op.batch_alter_table('subscriptions', schema=None) as batch_op:
        batch_op.alter_column('organization_id',
            existing_type=sa.VARCHAR(length=255),
            type_=sa.Text(),
            existing_nullable=False)
        batch_op.alter_column('plan',
            existing_type=sa.VARCHAR(length=50),
            type_=sa.Text(),
            existing_nullable=False)
        batch_op.alter_column('employee_limit',
            existing_type=sa.INTEGER(),
            type_=sa.Integer(),
            existing_nullable=False)
        batch_op.alter_column('start_date',
            existing_type=sa.DATE(),
            type_=sa.DateTime(),
            existing_nullable=False,
            postgresql_using='start_date::timestamp')
        batch_op.alter_column('end_date',
            existing_type=sa.DATE(),
            type_=sa.DateTime(),
            existing_nullable=False,
            postgresql_using='end_date::timestamp')
        batch_op.create_foreign_key('subscriptions_organization_id_fkey', 'users', ['organization_id'], ['username'])

    with op.batch_alter_table('rooms', schema=None) as batch_op:
        batch_op.alter_column('room_id',
            existing_type=sa.VARCHAR(length=50),
            type_=sa.Text(),
            existing_nullable=False)
        batch_op.alter_column('room_type',
            existing_type=sa.VARCHAR(length=50),
            type_=sa.Text(),
            existing_nullable=False)
        batch_op.alter_column('status',
            existing_type=sa.VARCHAR(length=20),
            type_=sa.Text(),
            existing_nullable=False,
            existing_server_default='available',
            server_default='available')

    with op.batch_alter_table('guests', schema=None) as batch_op:
        batch_op.alter_column('guest_id',
            existing_type=sa.INTEGER(),
            type_=sa.Text(),
            existing_nullable=False)
        batch_op.alter_column('name',
            existing_type=sa.VARCHAR(length=100),
            type_=sa.Text(),
            existing_nullable=False)
        batch_op.alter_column('room_id',
            existing_type=sa.VARCHAR(length=50),
            type_=sa.Text(),
            existing_nullable=True)
        batch_op.alter_column('check_in_date',
            existing_type=sa.DATE(),
            type_=sa.DateTime(),
            existing_nullable=True,
            postgresql_using='check_in_date::timestamp')
        batch_op.alter_column('check_out_date',
            existing_type=sa.DATE(),
            type_=sa.DateTime(),
            existing_nullable=True,
            postgresql_using='check_out_date::timestamp')
        batch_op.alter_column('status',
            existing_type=sa.VARCHAR(length=20),
            type_=sa.Text(),
            existing_nullable=False,
            existing_server_default='completed',
            server_default='completed')
        op.execute("DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'guests_room_id_fkey') THEN ALTER TABLE guests ADD CONSTRAINT guests_room_id_fkey FOREIGN KEY (room_id) REFERENCES rooms (room_id); END IF; END $$;")

    with op.batch_alter_table('configurations', schema=None) as batch_op:
        batch_op.alter_column('config_key',
            existing_type=sa.VARCHAR(length=255),
            type_=sa.Text(),
            existing_nullable=False)
        batch_op.alter_column('config_value',
            existing_type=postgresql.JSONB(astext_type=sa.Text()),
            type_=sa.Text(),
            existing_nullable=False)

    with op.batch_alter_table('audit_log', schema=None) as batch_op:
        batch_op.alter_column('id',
            existing_type=sa.INTEGER(),
            type_=sa.Integer(),
            existing_nullable=False)
        batch_op.alter_column('employee_id',
            existing_type=sa.VARCHAR(length=50),
            type_=sa.Text(),
            existing_nullable=True,
            nullable=False)
        batch_op.alter_column('action',
            existing_type=sa.VARCHAR(length=100),
            type_=sa.Text(),
            existing_nullable=True,
            nullable=False)
        batch_op.alter_column('timestamp',
            existing_type=postgresql.TIMESTAMP(timezone=True),
            type_=sa.DateTime(),
            existing_nullable=True,
            postgresql_using='timestamp::timestamp without time zone')

    # Add indexes with conditional table existence check
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.create_index('idx_users_username', ['username'])
    with op.batch_alter_table('verification_tokens', schema=None) as batch_op:
        batch_op.create_index('idx_verification_tokens_user_id', ['user_id'])
    with op.batch_alter_table('employees', schema=None) as batch_op:
        batch_op.create_index('idx_employees_organization_id', ['organization_id'])
    with op.batch_alter_table('audit_log', schema=None) as batch_op:
        batch_op.create_index('idx_audit_log_employee_id', ['employee_id'])
    with op.batch_alter_table('attendance', schema=None) as batch_op:
        batch_op.create_index('idx_attendance_employee_id', ['employee_id'])
    with op.batch_alter_table('subscriptions', schema=None) as batch_op:
        batch_op.create_index('idx_subscriptions_organization_id', ['organization_id'])
    with op.batch_alter_table('rooms', schema=None) as batch_op:
        batch_op.create_index('idx_rooms_room_id', ['room_id'])
    op.execute("DO $$ BEGIN IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'bookings') THEN PERFORM 1; ELSE RAISE NOTICE 'Table bookings does not exist, skipping index creation'; END IF; END $$;")
    with op.batch_alter_table('bookings', schema=None) as batch_op:
        batch_op.create_index('idx_bookings_room_id', ['room_id'])
    with op.batch_alter_table('guests', schema=None) as batch_op:
        batch_op.create_index('idx_guests_room_id', ['room_id'])
    with op.batch_alter_table('transactions', schema=None) as batch_op:
        batch_op.create_index('idx_transactions_username', ['username'])
    with op.batch_alter_table('configurations', schema=None) as batch_op:
        batch_op.create_index('idx_configurations_config_key', ['config_key'])
    with op.batch_alter_table('qr_codes', schema=None) as batch_op:
        batch_op.create_index('idx_qr_codes_qr_code', ['qr_code'], unique=True)

def downgrade():
    # Revert changes (optional)
    with op.batch_alter_table('qr_codes', schema=None) as batch_op:
        batch_op.drop_index('idx_qr_codes_qr_code')
    with op.batch_alter_table('configurations', schema=None) as batch_op:
        batch_op.drop_index('idx_configurations_config_key')
    with op.batch_alter_table('transactions', schema=None) as batch_op:
        batch_op.drop_index('idx_transactions_username')
    with op.batch_alter_table('guests', schema=None) as batch_op:
        batch_op.drop_index('idx_guests_room_id')
    op.execute("DO $$ BEGIN IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'bookings') THEN PERFORM 1; ELSE RAISE NOTICE 'Table bookings does not exist, skipping index drop'; END IF; END $$;")
    with op.batch_alter_table('bookings', schema=None) as batch_op:
        batch_op.drop_index('idx_bookings_room_id')
    with op.batch_alter_table('rooms', schema=None) as batch_op:
        batch_op.drop_index('idx_rooms_room_id')
    with op.batch_alter_table('subscriptions', schema=None) as batch_op:
        batch_op.drop_index('idx_subscriptions_organization_id')
    with op.batch_alter_table('attendance', schema=None) as batch_op:
        batch_op.drop_index('idx_attendance_employee_id')
    with op.batch_alter_table('audit_log', schema=None) as batch_op:
        batch_op.drop_index('idx_audit_log_employee_id')
    with op.batch_alter_table('employees', schema=None) as batch_op:
        batch_op.drop_index('idx_employees_organization_id')
    with op.batch_alter_table('verification_tokens', schema=None) as batch_op:
        batch_op.drop_index('idx_verification_tokens_user_id')
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_index('idx_users_username')

    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.alter_column('role',
            existing_type=sa.Text(),
            type_=sa.VARCHAR(length=20),
            existing_nullable=False,
            existing_server_default='admin')
        batch_op.alter_column('password_hash',
            existing_type=sa.Text(),
            type_=sa.VARCHAR(length=255),
            existing_nullable=False)
        batch_op.alter_column('username',
            existing_type=sa.Text(),
            type_=sa.VARCHAR(length=50),
            existing_nullable=False)

    with op.batch_alter_table('employees', schema=None) as batch_op:
        batch_op.drop_constraint('employees_organization_id_fkey', type_='foreignkey')
        batch_op.drop_column('organization_id')
        batch_op.drop_column('role')
        batch_op.drop_column('email')
        batch_op.alter_column('fingerprint_template',
            existing_type=sa.Text(),
            type_=postgresql.BYTEA(),
            existing_nullable=False)
        batch_op.alter_column('name',
            existing_type=sa.Text(),
            type_=sa.VARCHAR(length=100),
            existing_nullable=False)
        batch_op.alter_column('employee_id',
            existing_type=sa.Text(),
            type_=sa.VARCHAR(length=50),
            existing_nullable=False)

    with op.batch_alter_table('attendance', schema=None) as batch_op:
        batch_op.alter_column('fingerprint',
            existing_type=sa.Text(),
            type_=postgresql.BYTEA(),
            existing_nullable=True)
        batch_op.alter_column('timestamp',
            existing_type=sa.DateTime(),
            type_=postgresql.TIMESTAMP(timezone=True),
            existing_nullable=True)
        batch_op.alter_column('time_out',
            existing_type=sa.DateTime(),
            type_=postgresql.TIME(),
            existing_nullable=True)
        batch_op.alter_column('time_in',
            existing_type=sa.DateTime(),
            type_=postgresql.TIME(),
            existing_nullable=True)
        batch_op.alter_column('date',
            existing_type=sa.DateTime(),
            type_=sa.DATE(),
            existing_nullable=False)
        batch_op.alter_column('name',
            existing_type=sa.Text(),
            type_=sa.VARCHAR(length=100),
            existing_nullable=True)
        batch_op.alter_column('employee_id',
            existing_type=sa.Text(),
            type_=sa.VARCHAR(length=50),
            existing_nullable=False)

    with op.batch_alter_table('subscriptions', schema=None) as batch_op:
        batch_op.drop_constraint('subscriptions_organization_id_fkey', type_='foreignkey')
        batch_op.alter_column('end_date',
            existing_type=sa.DateTime(),
            type_=sa.DATE(),
            existing_nullable=False)
        batch_op.alter_column('start_date',
            existing_type=sa.DateTime(),
            type_=sa.DATE(),
            existing_nullable=False)
        batch_op.alter_column('employee_limit',
            existing_type=sa.Integer(),
            type_=sa.INTEGER(),
            existing_nullable=False)
        batch_op.alter_column('plan',
            existing_type=sa.Text(),
            type_=sa.VARCHAR(length=50),
            existing_nullable=False)
        batch_op.alter_column('organization_id',
            existing_type=sa.Text(),
            type_=sa.VARCHAR(length=255),
            existing_nullable=False)

    with op.batch_alter_table('rooms', schema=None) as batch_op:
        batch_op.alter_column('status',
            existing_type=sa.Text(),
            type_=sa.VARCHAR(length=20),
            existing_nullable=False,
            existing_server_default='available')
        batch_op.alter_column('room_type',
            existing_type=sa.Text(),
            type_=sa.VARCHAR(length=50),
            existing_nullable=False)
        batch_op.alter_column('room_id',
            existing_type=sa.Text(),
            type_=sa.VARCHAR(length=50),
            existing_nullable=False)

    with op.batch_alter_table('guests', schema=None) as batch_op:
        batch_op.drop_constraint('guests_room_id_fkey', type_='foreignkey')
        batch_op.alter_column('status',
            existing_type=sa.Text(),
            type_=sa.VARCHAR(length=20),
            existing_nullable=False,
            existing_server_default='completed')
        batch_op.alter_column('check_out_date',
            existing_type=sa.DateTime(),
            type_=sa.DATE(),
            existing_nullable=True)
        batch_op.alter_column('check_in_date',
            existing_type=sa.DateTime(),
            type_=sa.DATE(),
            existing_nullable=True)
        batch_op.alter_column('room_id',
            existing_type=sa.Text(),
            type_=sa.VARCHAR(length=50),
            existing_nullable=True)
        batch_op.alter_column('name',
            existing_type=sa.Text(),
            type_=sa.VARCHAR(length=100),
            existing_nullable=False)
        batch_op.alter_column('guest_id',
            existing_type=sa.INTEGER(),
            type_=sa.Text(),
            existing_nullable=False)

    with op.batch_alter_table('configurations', schema=None) as batch_op:
        batch_op.alter_column('config_value',
            existing_type=sa.Text(),
            type_=postgresql.JSONB(astext_type=sa.Text()),
            existing_nullable=False)
        batch_op.alter_column('config_key',
            existing_type=sa.Text(),
            type_=sa.VARCHAR(length=255),
            existing_nullable=False)

    with op.batch_alter_table('audit_log', schema=None) as batch_op:
        batch_op.alter_column('action',
            existing_type=sa.VARCHAR(length=100),
            type_=sa.Text(),
            existing_nullable=True,
            nullable=False)
        batch_op.alter_column('employee_id',
            existing_type=sa.VARCHAR(length=50),
            type_=sa.Text(),
            existing_nullable=True,
            nullable=False)
        batch_op.alter_column('timestamp',
            existing_type=postgresql.TIMESTAMP(timezone=True),
            type_=sa.DateTime(),
            existing_nullable=True,
            postgresql_using='timestamp::timestamp without time zone')
        batch_op.alter_column('id',
            existing_type=sa.INTEGER(),
            type_=sa.Integer(),
            existing_nullable=False)

    op.drop_table('verification_tokens')  # Clean up if created