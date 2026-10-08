# app/services/paper_trading.py
from utils.authorization import get_connection
import psycopg2.extras
from datetime import datetime
import logging

logger = logging.getLogger("paper-trading")

class PaperTradingEngine:
    """Motor de trading simulado sin dinero real"""
    
    def __init__(self):
        self.initial_balance = 10000.0
    
    def init_paper_tables(self):
        """Crea las tablas de paper trading"""
        conn = get_connection()
        cursor = conn.cursor()
        
        # Tabla de wallet
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS paper_wallet (
                id SERIAL PRIMARY KEY,
                usuario_id INTEGER UNIQUE REFERENCES usuarios(id) ON DELETE CASCADE,
                balance_usdt NUMERIC(18, 8) DEFAULT 10000,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Tabla de posiciones
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS paper_positions (
                id SERIAL PRIMARY KEY,
                usuario_id INTEGER REFERENCES usuarios(id) ON DELETE CASCADE,
                symbol VARCHAR(20) NOT NULL,
                side VARCHAR(10) NOT NULL,
                quantity NUMERIC(18, 8) NOT NULL,
                entry_price NUMERIC(18, 8) NOT NULL,
                current_price NUMERIC(18, 8),
                opened_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                closed_at TIMESTAMP,
                pnl NUMERIC(18, 8),
                status VARCHAR(20) DEFAULT 'OPEN'
            )
        ''')
        
        # Tabla de trades simulados
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS paper_trades (
                id SERIAL PRIMARY KEY,
                usuario_id INTEGER REFERENCES usuarios(id) ON DELETE CASCADE,
                symbol VARCHAR(20) NOT NULL,
                side VARCHAR(10) NOT NULL,
                quantity NUMERIC(18, 8) NOT NULL,
                price NUMERIC(18, 8) NOT NULL,
                total_value NUMERIC(18, 8) NOT NULL,
                trade_type VARCHAR(20) DEFAULT 'MARKET',
                executed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        conn.commit()
        conn.close()
    
    def get_or_create_wallet(self, usuario_id):
        """Obtiene o crea la wallet del usuario"""
        conn = get_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        
        cursor.execute(
            "SELECT * FROM paper_wallet WHERE usuario_id = %s",
            (usuario_id,)
        )
        wallet = cursor.fetchone()
        
        if not wallet:
            cursor.execute('''
                INSERT INTO paper_wallet (usuario_id, balance_usdt)
                VALUES (%s, %s)
                RETURNING *
            ''', (usuario_id, self.initial_balance))
            wallet = cursor.fetchone()
            conn.commit()
        
        conn.close()
        return dict(wallet)
    
    def execute_market_order(self, usuario_id, symbol, side, quantity, current_price):
        """Ejecuta una orden de mercado simulada"""
        wallet = self.get_or_create_wallet(usuario_id)
        total_value = quantity * current_price
        
        conn = get_connection()
        cursor = conn.cursor()
        
        if side == "BUY":
            # Verificar balance suficiente
            if wallet['balance_usdt'] < total_value:
                conn.close()
                raise ValueError(f"Balance insuficiente. Necesitas ${total_value:.2f}, tienes ${wallet['balance_usdt']:.2f}")
            
            # Descontar del balance
            cursor.execute('''
                UPDATE paper_wallet 
                SET balance_usdt = balance_usdt - %s 
                WHERE usuario_id = %s
            ''', (total_value, usuario_id))
        
        elif side == "SELL":
            # Verificar que tiene la posición
            cursor.execute('''
                SELECT * FROM paper_positions 
                WHERE usuario_id = %s AND symbol = %s AND status = 'OPEN'
            ''', (usuario_id, symbol))
            
            position = cursor.fetchone()
            if not position:
                conn.close()
                raise ValueError(f"No tienes posición abierta en {symbol}")
            
            # Agregar al balance
            cursor.execute('''
                UPDATE paper_wallet 
                SET balance_usdt = balance_usdt + %s 
                WHERE usuario_id = %s
            ''', (total_value, usuario_id))
        
        # Registrar el trade
        cursor.execute('''
            INSERT INTO paper_trades (
                usuario_id, symbol, side, quantity, price, total_value
            ) VALUES (%s, %s, %s, %s, %s, %s)
        ''', (usuario_id, symbol, side, quantity, current_price, total_value))
        
        # Actualizar o crear posición
        if side == "BUY":
            cursor.execute('''
                INSERT INTO paper_positions (
                    usuario_id, symbol, side, quantity, entry_price, current_price
                ) VALUES (%s, %s, %s, %s, %s, %s)
            ''', (usuario_id, symbol, side, quantity, current_price, current_price))
        elif side == "SELL":
            # Calcular P&L
            cursor.execute('''
                SELECT entry_price, quantity FROM paper_positions 
                WHERE usuario_id = %s AND symbol = %s AND status = 'OPEN'
                LIMIT 1
            ''', (usuario_id, symbol))
            
            pos = cursor.fetchone()
            if pos:
                entry_price = pos[0]
                pnl = (current_price - entry_price) * quantity
                
                cursor.execute('''
                    UPDATE paper_positions 
                    SET status = 'CLOSED', closed_at = CURRENT_TIMESTAMP, 
                        current_price = %s, pnl = %s
                    WHERE usuario_id = %s AND symbol = %s AND status = 'OPEN'
                ''', (current_price, pnl, usuario_id, symbol))
        
        conn.commit()
        conn.close()
        
        return {
            "success": True,
            "symbol": symbol,
            "side": side,
            "quantity": quantity,
            "price": current_price,
            "total_value": total_value
        }
    
    def get_portfolio_summary(self, usuario_id):
        """Resumen del portfolio de paper trading"""
        conn = get_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        
        # Wallet
        cursor.execute("SELECT * FROM paper_wallet WHERE usuario_id = %s", (usuario_id,))
        wallet = cursor.fetchone()
        
        # Posiciones abiertas
        cursor.execute('''
            SELECT * FROM paper_positions 
            WHERE usuario_id = %s AND status = 'OPEN'
        ''', (usuario_id,))
        open_positions = [dict(p) for p in cursor.fetchall()]
        
        # Trades totales
        cursor.execute('''
            SELECT COUNT(*) as total_trades,
                   COALESCE(SUM(CASE WHEN side = 'BUY' THEN total_value END), 0) as total_compras,
                   COALESCE(SUM(CASE WHEN side = 'SELL' THEN total_value END), 0) as total_ventas
            FROM paper_trades 
            WHERE usuario_id = %s
        ''', (usuario_id,))
        stats = cursor.fetchone()
        
        conn.close()
        
        return {
            "wallet": dict(wallet) if wallet else None,
            "open_positions": open_positions,
            "stats": dict(stats)
        }

# Instancia global
paper_engine = PaperTradingEngine()
paper_engine.init_paper_tables()