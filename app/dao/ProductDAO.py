from app.connections.intensive_review_db_conn import IntensiveReviewConnection
"""
Intensive Review
    Write a function that inserts a record into SQLite.
"""

class ProductDAO:

    def save_product_db(self, name, price):
        conn = IntensiveReviewConnection().get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO Product (name, price) VALUES (?, ?)",
            (name, price),
        )
        product_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return product_id

