import sqlite3


def create_dummy_db():
    conn = sqlite3.connect("customers.db")
    cursor = conn.cursor()

    # Création de la table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS customers (
            id INTEGER PRIMARY KEY,
            name TEXT,
            email TEXT,
            status TEXT,
            total_spend REAL
        )
    """)

    # Ajout de fausses données
    customers = [
        (1, "Yaniv Bohbot", "yanivbohbot5@gmail.com", "VIP", 15000.50),
        (2, "Alice Dupont", "alice@example.com", "Standard", 120.00),
        (3, "Bob Martin", "bob@example.com", "Premium", 4500.00),
        (4, "Martin Levy", "MartinLevy@example.com", "Premium", 84740.00),
        (5, "Yann Checkroun", "yanoosss@example.com", "Premium", 4500.00),
        (6, "JAmes Bond", "jamesbond@example.com", "Premium", 4500.00),
    ]

    cursor.executemany(
        "INSERT OR REPLACE INTO customers VALUES (?, ?, ?, ?, ?)", customers
    )
    conn.commit()
    conn.close()
    print("✅ Base de données 'customers.db' créée avec succès.")


if __name__ == "__main__":
    create_dummy_db()
