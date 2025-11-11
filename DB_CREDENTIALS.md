# Database Credentials

## PostgreSQL Connection Details

- **Host**: localhost
- **Port**: 5432
- **Database Name**: washdb
- **Username**: washbot
- **Password**: Washdb123

## Connection String

For SQLAlchemy or psycopg:
```
postgresql://washbot:Washdb123@localhost:5432/washdb
```

## psql CLI Connection

```bash
psql -h localhost -U washbot -d washdb
```

## Verify Connection

```bash
psql -U postgres -c "\l" | grep washdb
psql -U postgres -c "\du" | grep washbot
```

## Note

- Store actual credentials in `.env` file (add to .gitignore)
- Use `.env.example` as a template for other developers
