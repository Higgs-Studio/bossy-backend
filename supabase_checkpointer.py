"""
Custom Supabase REST API Checkpointer for LangGraph.

This module provides a checkpointer implementation that uses Supabase REST API
instead of direct PostgreSQL connections, making it compatible with serverless
deployments like Vercel.
"""

import json
import logging
from datetime import datetime
from typing import Dict, Any, Optional, List

from supabase import Client as SupabaseClient
from langgraph.checkpoint.base import BaseCheckpointSaver, Checkpoint, CheckpointMetadata, CheckpointTuple

logger = logging.getLogger(__name__)


class SupabaseRESTCheckpointer(BaseCheckpointSaver):
    """
    Custom checkpointer that uses Supabase REST API instead of direct PostgreSQL connection.
    This is compatible with serverless deployments like Vercel.
    """
    
    def __init__(self, supabase_client: SupabaseClient):
        self.supabase = supabase_client
        self._setup_tables()
    
    def _setup_tables(self):
        """Create checkpoint tables if they don't exist using Supabase REST API."""
        # Note: Table creation must be done via SQL in Supabase dashboard
        # This method just verifies tables exist (they should be created via setup_checkpoint_tables.sql)
        pass
    
    def setup(self):
        """Setup checkpoint tables. Tables should be created via SQL script."""
        # Tables are created via setup_checkpoint_tables.sql in Supabase
        # This method is kept for compatibility
        logger.info("Supabase REST checkpointer setup - ensure tables exist via SQL script")
    
    def put(
        self,
        config: Dict[str, Any],
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Save a checkpoint using Supabase REST API."""
        thread_id = config.get("configurable", {}).get("thread_id", "")
        checkpoint_ns = config.get("configurable", {}).get("checkpoint_ns", "")
        
        # Generate checkpoint_id if not present
        checkpoint_id = checkpoint.get("id") if isinstance(checkpoint, dict) else str(checkpoint.id) if hasattr(checkpoint, 'id') else str(datetime.now().timestamp())
        parent_checkpoint_id = checkpoint.get("parent_id") if isinstance(checkpoint, dict) else (checkpoint.parent_id if hasattr(checkpoint, 'parent_id') else None)
        
        try:
            # Convert checkpoint to dict if it's an object
            if not isinstance(checkpoint, dict):
                checkpoint_dict = checkpoint.dict() if hasattr(checkpoint, 'dict') else json.loads(json.dumps(checkpoint, default=str))
            else:
                checkpoint_dict = checkpoint
            
            # Prepare checkpoint data - store as JSONB
            checkpoint_data = {
                "thread_id": thread_id,
                "checkpoint_ns": checkpoint_ns or "",
                "checkpoint_id": checkpoint_id,
                "checkpoint": checkpoint_dict,
                "parent_checkpoint_id": parent_checkpoint_id,
                "metadata": metadata if metadata else {}
            }
            
            # Upsert checkpoint (insert or update if exists)
            # Check if checkpoint exists first
            existing = self.supabase.table("checkpoints").select("checkpoint_id").eq("thread_id", thread_id).eq("checkpoint_ns", checkpoint_ns or "").eq("checkpoint_id", checkpoint_id).execute()
            
            if existing.data and len(existing.data) > 0:
                # Update existing checkpoint
                self.supabase.table("checkpoints").update({
                    "checkpoint": checkpoint_dict,
                    "parent_checkpoint_id": parent_checkpoint_id,
                    "metadata": metadata if metadata else {}
                }).eq("thread_id", thread_id).eq("checkpoint_ns", checkpoint_ns or "").eq("checkpoint_id", checkpoint_id).execute()
            else:
                # Insert new checkpoint
                self.supabase.table("checkpoints").insert(checkpoint_data).execute()
            
            # Handle blobs if any
            if new_versions:
                for channel, version_data in new_versions.items():
                    if isinstance(version_data, dict):
                        version = version_data.get("version", str(datetime.now().timestamp()))
                        blob_data = {
                            "thread_id": thread_id,
                            "checkpoint_ns": checkpoint_ns or "",
                            "channel": channel,
                            "version": version,
                            "type": version_data.get("type"),
                            "blob": version_data.get("blob")
                        }
                        # Check if blob exists
                        existing_blob = self.supabase.table("checkpoint_blobs").select("version").eq("thread_id", thread_id).eq("checkpoint_ns", checkpoint_ns or "").eq("channel", channel).eq("version", version).execute()
                        
                        if existing_blob.data and len(existing_blob.data) > 0:
                            # Update existing blob
                            self.supabase.table("checkpoint_blobs").update({
                                "type": version_data.get("type"),
                                "blob": version_data.get("blob")
                            }).eq("thread_id", thread_id).eq("checkpoint_ns", checkpoint_ns or "").eq("channel", channel).eq("version", version).execute()
                        else:
                            # Insert new blob
                            self.supabase.table("checkpoint_blobs").insert(blob_data).execute()
            
            return {"configurable": {"thread_id": thread_id, "checkpoint_ns": checkpoint_ns}}
            
        except Exception as e:
            logger.error(f"Error saving checkpoint: {e}")
            raise
    
    def get(self, config: Dict[str, Any]) -> Optional[CheckpointTuple]:
        """Retrieve a checkpoint using Supabase REST API."""
        thread_id = config.get("configurable", {}).get("thread_id", "")
        checkpoint_ns = config.get("configurable", {}).get("checkpoint_ns", "")
        checkpoint_id = config.get("configurable", {}).get("checkpoint_id")
        
        try:
            query = self.supabase.table("checkpoints").select("*").eq("thread_id", thread_id).eq("checkpoint_ns", checkpoint_ns or "")
            
            if checkpoint_id:
                query = query.eq("checkpoint_id", checkpoint_id)
            else:
                # Get the latest checkpoint - order by checkpoint_id descending
                # Note: Supabase ordering syntax
                query = query.order("checkpoint_id", desc=True).limit(1)
            
            result = query.execute()
            
            if not result.data or len(result.data) == 0:
                return None
            
            checkpoint_row = result.data[0]
            checkpoint = checkpoint_row.get("checkpoint", {})
            metadata = checkpoint_row.get("metadata", {})
            parent_checkpoint_id = checkpoint_row.get("parent_checkpoint_id")
            
            # Build parent_config if parent exists
            parent_config = None
            if parent_checkpoint_id:
                parent_config = {
                    "configurable": {
                        "thread_id": thread_id,
                        "checkpoint_ns": checkpoint_ns,
                        "checkpoint_id": parent_checkpoint_id
                    }
                }
            
            return CheckpointTuple(
                config={"configurable": {"thread_id": thread_id, "checkpoint_ns": checkpoint_ns}},
                checkpoint=checkpoint,
                metadata=metadata,
                parent_config=parent_config
            )
            
        except Exception as e:
            logger.error(f"Error retrieving checkpoint: {e}")
            return None
    
    def list(
        self,
        config: Dict[str, Any],
        filter: Optional[Dict[str, Any]] = None,
        before: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[CheckpointTuple]:
        """List checkpoints using Supabase REST API."""
        thread_id = config.get("configurable", {}).get("thread_id", "")
        checkpoint_ns = config.get("configurable", {}).get("checkpoint_ns", "")
        
        try:
            query = self.supabase.table("checkpoints").select("*").eq("thread_id", thread_id).eq("checkpoint_ns", checkpoint_ns or "")
            
            if before:
                # Use less than comparison for checkpoint_id
                query = query.lt("checkpoint_id", before)
            
            if limit:
                query = query.limit(limit)
            
            # Order by checkpoint_id descending
            query = query.order("checkpoint_id", desc=True)
            
            result = query.execute()
            
            checkpoints = []
            for row in result.data:
                checkpoint = row.get("checkpoint", {})
                metadata = row.get("metadata", {})
                parent_checkpoint_id = row.get("parent_checkpoint_id")
                
                parent_config = None
                if parent_checkpoint_id:
                    parent_config = {
                        "configurable": {
                            "thread_id": thread_id,
                            "checkpoint_ns": checkpoint_ns,
                            "checkpoint_id": parent_checkpoint_id
                        }
                    }
                
                checkpoints.append(CheckpointTuple(
                    config={"configurable": {"thread_id": thread_id, "checkpoint_ns": checkpoint_ns}},
                    checkpoint=checkpoint,
                    metadata=metadata,
                    parent_config=parent_config
                ))
            
            return checkpoints
            
        except Exception as e:
            logger.error(f"Error listing checkpoints: {e}")
            return []
