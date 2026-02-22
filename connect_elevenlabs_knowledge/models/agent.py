from odoo import fields, models
import logging

logger = logging.getLogger(__name__)


class ElevenlabsAgent(models.Model):
    _inherit = 'connect.elevenlabs_agent'

    knowledge_base = fields.Many2many(
        'connect.elevenlabs_knowledge',
        'agent_knowledge_rel',
        'agent_id',
        'knowledge_id',
        string='Knowledge Base Documents'
    )

    def _compute_prompt_config(self):
        """Override to include knowledge base in agent prompt configuration"""
        prompt_dict = super()._compute_prompt_config()
        if not self.knowledge_base:
            prompt_dict['knowledge_base'] = []
        else:
            prompt_dict['knowledge_base'] = [{
                "type": "text",
                "name": doc.name,
                "id": doc.knowledge_id,
            } for doc in self.knowledge_base if doc.knowledge_id and doc.state == 'active']
        return prompt_dict
    
    def add_knowledge_documents(self, knowledge_ids):
        """Add knowledge documents to this agent"""
        self.ensure_one()
        if not knowledge_ids:
            return False
        
        # Convert to list if single ID
        if isinstance(knowledge_ids, int):
            knowledge_ids = [knowledge_ids]
        
        # Add knowledge documents
        self.write({'knowledge_base': [(4, kid) for kid in knowledge_ids]})
        
        # Sync with ElevenLabs
        if not self.env.context.get('skip_elevenlabs'):
            self.update_elevenlabs_agent()
        
        logger.info(f'Added {len(knowledge_ids)} knowledge documents to agent "{self.name}"')
        return True
    
    def remove_knowledge_documents(self, knowledge_ids):
        """Remove knowledge documents from this agent"""
        self.ensure_one()
        if not knowledge_ids:
            return False
        
        # Convert to list if single ID
        if isinstance(knowledge_ids, int):
            knowledge_ids = [knowledge_ids]
        
        # Remove knowledge documents
        self.write({'knowledge_base': [(3, kid) for kid in knowledge_ids]})
        
        # Sync with ElevenLabs
        if not self.env.context.get('skip_elevenlabs'):
            self.update_elevenlabs_agent()
        
        logger.info(f'Removed {len(knowledge_ids)} knowledge documents from agent "{self.name}"')
        return True
    
    def clear_knowledge_base(self):
        """Remove all knowledge documents from this agent"""
        self.ensure_one()
        self.write({'knowledge_base': [(5, 0, 0)]})
        
        # Sync with ElevenLabs
        if not self.env.context.get('skip_elevenlabs'):
            self.update_elevenlabs_agent()
        
        logger.info(f'Cleared all knowledge documents from agent "{self.name}"')
        return True
