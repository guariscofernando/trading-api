# app/services/order_sync.py
from app.services.binance_service import binance_service
from app.dao.OrderDAO import OrderDAO
import logging

logger = logging.getLogger("order-sync")
dao = OrderDAO()

def sincronizar_ordenes():
    """Sincroniza el estado de órdenes con Binance"""
    # Obtener órdenes que no están en estado final
    estados_activos = ['NEW', 'PARTIALLY_FILLED']
    
    for status in estados_activos:
        orders = dao.obtener_orders_db(status=status, limit=100)
        
        for order in orders:
            try:
                # Consultar estado actual en Binance
                binance_order = binance_service.client.get_order(
                    symbol=order['symbol'],
                    orderId=order['binance_order_id']
                )
                
                # Actualizar en nuestra DB si cambió
                if binance_order['status'] != order['status']:
                    dao.actualizar_order_status_db(
                        binance_order_id=order['binance_order_id'],
                        status=binance_order['status'],
                        executed_qty=binance_order.get('executedQty', 0)
                    )
                    logger.info(
                        f"Orden {order['binance_order_id']} actualizada: "
                        f"{order['status']} → {binance_order['status']}"
                    )
                    
            except Exception as e:
                logger.error(f"Error sincronizando orden {order['binance_order_id']}: {e}")
    
    return {"message": "Sincronización completada"}