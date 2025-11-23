#!/usr/bin/env python3
import os
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()
engine = create_engine(os.getenv('DATABASE_URL'))

with engine.connect() as conn:
    result = conn.execute(text("""
        SELECT COUNT(*) as count
        FROM companies
        WHERE website IS NOT NULL
          AND (
              parse_metadata->'verification' IS NULL
              OR parse_metadata->'verification'->>'status' IS NULL
          )
    """))
    count = result.scalar()
    print(f'Unverified companies with website: {count}')
