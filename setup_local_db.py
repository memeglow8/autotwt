import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

def setup_local_database():
    """Create the local database if it doesn't exist"""
    try:
        # Connect to PostgreSQL server
        conn = psycopg2.connect(
            dbname='postgres',
            user='postgres',
            password='postgres',
            host='localhost'
        )
        conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        cur = conn.cursor()
        
        # Check if database exists
        cur.execute("SELECT 1 FROM pg_catalog.pg_database WHERE datname = 'taskair'")
        exists = cur.fetchone()
        
        if not exists:
            cur.execute('CREATE DATABASE taskair')
            print("Database 'taskair' created successfully")
        else:
            print("Database 'taskair' already exists")
            
        cur.close()
        conn.close()
        
        print("Local database setup completed")
        return True
        
    except psycopg2.Error as e:
        print(f"Error setting up local database: {e}")
        return False

if __name__ == "__main__":
    setup_local_database()
