"""Persistência MariaDB para estado, histórico e saúde do monitor Vinted."""

import os
import mysql.connector


def _credentials_from_file():
    path = os.environ.get("VINTED_DB_CREDENTIALS_FILE")
    values = {}
    if not path:
        return values
    with open(path, encoding="utf-8") as file:
        for line in file:
            key, sep, value = line.strip().partition("=")
            if sep and not key.startswith("#"):
                values[key] = value
    return values


def connect(include_database=True):
    shared = _credentials_from_file()
    config = {
        "host": os.environ.get("VINTED_DB_HOST", shared.get("DB_HOST", "localhost")),
        "port": int(os.environ.get("VINTED_DB_PORT", "3306")),
        "user": os.environ.get("VINTED_DB_USER", shared["DB_USER"]),
        "password": os.environ.get("VINTED_DB_PASSWORD", shared.get("DB_PASS", shared.get("DB_PASSWORD"))),
        "autocommit": True,
    }
    if include_database:
        config["database"] = os.environ.get("VINTED_DB_NAME", shared.get("DB_NAME", "vinted_monitor"))
    return mysql.connector.connect(**config)


def initialize():
    conn = connect()
    cur = conn.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS vinted_seen_items (
        item_id VARCHAR(32) PRIMARY KEY, last_price DECIMAL(10,2) NOT NULL,
        updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
    ) ENGINE=InnoDB""")
    cur.execute("""CREATE TABLE IF NOT EXISTS vinted_alerts (
        id BIGINT AUTO_INCREMENT PRIMARY KEY, item_id VARCHAR(32) NOT NULL,
        search_term VARCHAR(255) NOT NULL, title VARCHAR(500) NOT NULL,
        item_price DECIMAL(10,2) NOT NULL, total_price DECIMAL(10,2) NOT NULL,
        url VARCHAR(1000) NOT NULL, alert_type VARCHAR(32) NOT NULL,
        sent_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        INDEX idx_alerts_sent_at (sent_at), INDEX idx_alerts_item (item_id)
    ) ENGINE=InnoDB""")
    cur.execute("""CREATE TABLE IF NOT EXISTS vinted_monitor_health (
        id BIGINT AUTO_INCREMENT PRIMARY KEY, checked_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        level VARCHAR(16) NOT NULL, component VARCHAR(64) NOT NULL, message TEXT NOT NULL,
        INDEX idx_health_checked_at (checked_at)
    ) ENGINE=InnoDB""")
    cur.execute("""CREATE TABLE IF NOT EXISTS vinted_monitor_meta (
        meta_key VARCHAR(100) PRIMARY KEY, meta_value VARCHAR(255) NOT NULL,
        updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
    ) ENGINE=InnoDB""")
    cur.close()
    conn.close()


def load_seen_items():
    conn = connect(); cur = conn.cursor()
    cur.execute("SELECT item_id, last_price FROM vinted_seen_items")
    result = {str(item_id): float(price) for item_id, price in cur.fetchall()}
    cur.close(); conn.close()
    return result


def save_seen_items(items):
    if not items:
        return
    conn = connect(); cur = conn.cursor()
    cur.executemany("""INSERT INTO vinted_seen_items (item_id, last_price) VALUES (%s, %s)
        ON DUPLICATE KEY UPDATE last_price=VALUES(last_price)""", list(items.items()))
    cur.close(); conn.close()


def record_alert(item, search_term, alert_type):
    conn = connect(); cur = conn.cursor()
    cur.execute("""INSERT INTO vinted_alerts (item_id, search_term, title, item_price, total_price, url, alert_type)
        VALUES (%s, %s, %s, %s, %s, %s, %s)""", (item['id'], search_term, item['title'], item['price'], item['total_price'], item['url'], alert_type))
    cur.close(); conn.close()


def record_health(level, component, message):
    conn = connect(); cur = conn.cursor()
    cur.execute("INSERT INTO vinted_monitor_health (level, component, message) VALUES (%s, %s, %s)", (level, component, message))
    cur.close(); conn.close()


def prune(days=90):
    conn = connect(); cur = conn.cursor()
    cur.execute("DELETE FROM vinted_seen_items WHERE updated_at < NOW() - INTERVAL %s DAY", (days,))
    cur.execute("DELETE FROM vinted_alerts WHERE sent_at < NOW() - INTERVAL %s DAY", (days,))
    cur.execute("DELETE FROM vinted_monitor_health WHERE checked_at < NOW() - INTERVAL %s DAY", (days,))
    cur.close(); conn.close()
