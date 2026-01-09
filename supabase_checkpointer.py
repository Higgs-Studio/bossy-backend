"""
Custom Supabase AsyncPostgresSaver Checkpointer for LangGraph.

This module provides a checkpointer implementation using AsyncPostgresSaver
with Supabase PostgreSQL database, compatible with async LangGraph operations.
"""

import os
import logging
from typing import Optional
from dotenv import load_dotenv
from psycopg import AsyncConnection
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

load_dotenv()

logger = logging.getLogger(__name__)


class SupabaseCheckpointer:
    """Manage PostgreSQL connections and LangGraph checkpointing with Supabase using AsyncPostgresSaver"""
    
    def __init__(self, db_uri: Optional[str] = None):
        """
        Initialize the Supabase checkpointer.
        
        Args:
            db_uri: PostgreSQL connection URI. If not provided, reads from SUPABASE_DB_URI env var.
        """
        self._db_uri = db_uri or os.getenv("SUPABASE_DB_URI")
        if not self._db_uri:
            raise ValueError("SUPABASE_DB_URI environment variable or db_uri parameter is required")
        
        self.conn: Optional[AsyncConnection] = None
        self._checkpointer: Optional[AsyncPostgresSaver] = None
    
    async def setup_connection(self) -> None:
        """Initialize the database connection and checkpointer"""
        try:
            # If already connected, return early
            if self.conn and self._checkpointer:
                return
            
            # Parse connection string and ensure SSL is required for Supabase
            # psycopg 3 uses connection strings directly
            self.conn = await AsyncConnection.connect(
                self._db_uri,
                autocommit=True,  # Required for concurrent operations
            )
            
            self._checkpointer = AsyncPostgresSaver(self.conn)
            await self._checkpointer.setup()  # Creates tables if needed
            logger.info("Supabase AsyncPostgresSaver checkpointer initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize Supabase checkpointer: {e}")
            raise
    
    async def close_connection(self) -> None:
        """Close the database connection"""
        if self.conn:
            await self.conn.close()
            self.conn = None
            self._checkpointer = None
            logger.info("Supabase checkpointer connection closed")
    
    @property
    def checkpointer(self) -> Optional[AsyncPostgresSaver]:
        """Get the AsyncPostgresSaver checkpointer instance"""
        return self._checkpointer
    
    async def __aenter__(self):
        await self.setup_connection()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close_connection()
