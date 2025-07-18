from dataclasses import dataclass
from datetime import datetime

@dataclass
class UpdateMessage:
    update_id: str
    update_type: str
    payload: dict
    timestamp: datetime
    source_node: str
    
    def to_dict(self):
        return {
            'update_id': self.update_id,
            'update_type': self.update_type,
            'payload': self.payload,
            'timestamp': self.timestamp.isoformat(),
            'source_node': self.source_node
        }
    
    @classmethod
    def from_dict(cls, data: dict):
        data['timestamp'] = datetime.fromisoformat(data['timestamp'])
        return cls(**data)