package main

import (
	"database/sql"
	"log"
	"time"

	_ "github.com/lib/pq"
)

// OpenDB 打开 PG 连接池（与 backend/core 同库）。
func OpenDB(dsn string) (*sql.DB, error) {
	db, err := sql.Open("postgres", dsn)
	if err != nil {
		return nil, err
	}
	db.SetMaxOpenConns(8)
	db.SetMaxIdleConns(4)
	db.SetConnMaxLifetime(30 * time.Minute)
	if err = db.Ping(); err != nil {
		return nil, err
	}
	log.Println("db connected")
	return db, nil
}
