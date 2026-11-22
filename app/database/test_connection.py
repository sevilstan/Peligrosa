import asyncio
from sqlalchemy import text
from app.database.session import engine


async def main():
    if engine is None:
        print("HATA: DATABASE_URL okunamadı.")
        return

    try:
        async with engine.connect() as connection:
            result = await connection.execute(text("SELECT version()"))
            print("PostgreSQL bağlantısı başarılı!")
            print(result.scalar())

    except Exception as error:
        print("Bağlantı hatası:", error)

    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
