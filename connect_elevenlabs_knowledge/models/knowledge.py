import base64
import io
import json
import logging
import re

import requests

from odoo import api, fields, models
from odoo.exceptions import ValidationError

logger = logging.getLogger(__name__)


class ElevenlabsKnowledge(models.Model):
    _name = 'connect.elevenlabs_knowledge'
    _description = 'ElevenLabs Knowledge Base Document'

    name = fields.Char(required=True)
    knowledge_id = fields.Char()
    type = fields.Selection(selection=[('url', 'URL'), ('file', 'File'), ('text', 'Text')], required=True,
                            default='url')
    file_name = fields.Char()
    file = fields.Binary(attachment=True)
    url = fields.Char()
    text = fields.Text()
    
    # Enhanced fields for better management
    description = fields.Text()
    created_at = fields.Datetime(readonly=True)
    updated_at = fields.Datetime(readonly=True)
    document_size = fields.Integer(readonly=True, help="Size of the document in bytes")
    force_delete = fields.Boolean(default=False, help="Force delete even if used by agents")
    
    # Status tracking
    state = fields.Selection([
        ('draft', 'Draft'),
        ('creating', 'Creating'),
        ('active', 'Active'),
        ('error', 'Error')
    ], default='draft', readonly=True)
    error_message = fields.Text(readonly=True)
    
    # Agent relationships
    agent_ids = fields.Many2many(
        'connect.elevenlabs_agent',
        'agent_knowledge_rel',
        'knowledge_id',
        'agent_id',
        string='Agents Using This Knowledge'
    )
    agent_count = fields.Integer(compute='_compute_agent_count', string='Number of Agents')
    
    @api.depends('agent_ids')
    def _compute_agent_count(self):
        for record in self:
            record.agent_count = len(record.agent_ids)

    @api.constrains('file_name')
    def _check_knowledge_file_format(self):
        for knowledge in self:
            if type(knowledge.file_name) == bool:
                continue
            for extension in ['.epub', '.pdf', '.docx', '.txt', '.html']:
                if knowledge.file_name.endswith(extension):
                    return
            raise ValidationError('Invalid file type. Allowed formats is .epub, .pdf, .docx, .txt and .html')

    @api.model_create_multi
    def create(self, vals_list):
        res = super().create(vals_list)
        for rec in res:
            if not self.env.context.get('skip_elevenlabs'):
                rec.create_elevenlabs_knowledge_base()
        return res
    
    def write(self, vals):
        """Override write to handle name updates and agent changes via ElevenLabs API"""
        # Store old agent_ids before write if we need to track changes
        old_agent_ids = {}
        if 'agent_ids' in vals and not self.env.context.get('skip_elevenlabs'):
            for record in self:
                old_agent_ids[record.id] = set(record.agent_ids.ids)
        
        result = super().write(vals)
        
        # If name is being updated and we have a knowledge_id, update via API
        if 'name' in vals and not self.env.context.get('skip_elevenlabs'):
            for record in self:
                if record.knowledge_id and record.state == 'active':
                    try:
                        record.update_document_name(vals['name'])
                    except Exception as e:
                        # Log error but don't fail the write operation
                        logger.warning(f'Failed to update document name in ElevenLabs: {e}')
        
        # If agent_ids changed, sync all affected agents with ElevenLabs
        if 'agent_ids' in vals and not self.env.context.get('skip_elevenlabs'):
            for record in self:
                new_agent_ids = set(record.agent_ids.ids)
                old_ids = old_agent_ids.get(record.id, set())
                
                # Find which agents were added or removed
                added_agents = new_agent_ids - old_ids
                removed_agents = old_ids - new_agent_ids
                
                # Update all affected agents on ElevenLabs
                affected_agent_ids = added_agents | removed_agents
                if affected_agent_ids:
                    agents = self.env['connect.elevenlabs_agent'].browse(list(affected_agent_ids))
                    for agent in agents:
                        try:
                            agent.update_elevenlabs_agent()
                            logger.info(f'Synced agent "{agent.name}" with ElevenLabs after knowledge change')
                        except Exception as e:
                            logger.warning(f'Failed to sync agent "{agent.name}" with ElevenLabs: {e}')
        
        return result

    def unlink(self):
        for rec in self:
            rec.delete_elevenlabs_knowledge_base()
        res = super().unlink()
        return res

    def create_elevenlabs_knowledge_base(self):
        """Create knowledge base document with enhanced error handling"""
        self.write({'state': 'creating', 'error_message': False})
        
        try:
            client = self.env['connect.settings'].get_elevenlabs_client()
            if self.type == 'url':
                knowledge_base = client.conversational_ai.knowledge_base.documents.create_from_url(
                    name=self.name,
                    url=self.url,
                )
            elif self.type == 'text':
                knowledge_base = client.conversational_ai.knowledge_base.documents.create_from_text(
                    name=self.name,
                    text=self.text
                )
            else:
                file_bytes = base64.b64decode(self.file)
                file = io.BytesIO(file_bytes)
                file.name = self.file_name
                knowledge_base = client.conversational_ai.knowledge_base.documents.create_from_file(
                    name=self.name,
                    file=file
                )
            
            if knowledge_base:
                self.with_context(skip_elevenlabs=True).write({
                    'knowledge_id': knowledge_base.id,
                    'state': 'active',
                    'created_at': fields.Datetime.now(),
                    'updated_at': fields.Datetime.now()
                })
                logger.info(f'Successfully created knowledge base document: {self.name} (ID: {knowledge_base.id})')
                return True
            else:
                self.write({'state': 'error', 'error_message': 'Failed to create document - no response from API'})
                return False
                
        except Exception as e:
            error_msg = f'Error creating knowledge base document: {str(e)}'
            logger.error(error_msg)
            self.write({'state': 'error', 'error_message': error_msg})
            return False

    def delete_elevenlabs_knowledge_base(self):
        """Delete knowledge base document with enhanced error handling and force option"""
        if self.knowledge_id:
            try:
                client = self.env['connect.settings'].get_elevenlabs_client()
                client.conversational_ai.knowledge_base.documents.delete(
                    documentation_id=self.knowledge_id,
                    force=self.force_delete
                )
                logger.info(f'Successfully deleted knowledge base document: {self.name} (ID: {self.knowledge_id})')
            except Exception as e:
                error_msg = f'Error deleting knowledge base document "{self.name}": {str(e)}'
                logger.error(error_msg)
                match = re.search(r"body:\s*(\{.*\})", error_msg)
                if match:
                    body_str = match.group(1)
                    body_json = json.loads(body_str.replace("'", '"'))
                    error_msg = body_json["detail"]["message"]
                raise ValidationError(error_msg)
    
    def update_document_name(self, new_name):
        """Update the document name using the latest API"""
        if not self.knowledge_id:
            raise ValidationError('Cannot update document: not yet created in ElevenLabs')
        
        try:
            client = self.env['connect.settings'].get_elevenlabs_client()
            client.conversational_ai.knowledge_base.documents.update(
                documentation_id=self.knowledge_id,
                name=new_name
            )
            self.with_context(skip_elevenlabs=True).write({
                'name': new_name,
                'updated_at': fields.Datetime.now()
            })
            logger.info(f'Successfully updated document name to: {new_name} (ID: {self.knowledge_id})')
            return True
            
        except Exception as e:
            error_msg = f'Error updating document name: {str(e)}'
            logger.error(error_msg)
            raise ValidationError(error_msg)
    
    @api.model
    def sync_with_elevenlabs(self, page_size=30, search_term=None):
        """Sync local records with ElevenLabs knowledge base using the list API"""
        try:
            client = self.env['connect.settings'].get_elevenlabs_client()
            response = client.conversational_ai.knowledge_base.list(
                page_size=page_size,
                search=search_term,
                show_only_owned_documents=True
            )
            
            synced_count = 0
            for doc in response.documents:
                existing = self.search([('knowledge_id', '=', doc.id)], limit=1)
                if not existing:
                    # Create new record for documents found in ElevenLabs but not in Odoo
                    self.with_context(skip_elevenlabs=True).create({
                        'name': doc.name,
                        'knowledge_id': doc.id,
                        'type': 'url',  # Default type, may need adjustment
                        'state': 'active',
                        'description': getattr(doc, 'description', ''),
                        'document_size': getattr(doc, 'size', 0),
                        'created_at': fields.Datetime.now(),
                        'updated_at': fields.Datetime.now(),
                    })
                    synced_count += 1
                else:
                    # Update existing record
                    existing.with_context(skip_elevenlabs=True).write({
                        'name': doc.name,
                        'description': getattr(doc, 'description', ''),
                        'document_size': getattr(doc, 'size', 0),
                        'updated_at': fields.Datetime.now(),
                    })
            
            logger.info(f'Synced {synced_count} documents from ElevenLabs')
            return {'synced_count': synced_count, 'total_found': len(response.documents)}
            
        except Exception as e:
            error_msg = f'Error syncing with ElevenLabs: {str(e)}'
            logger.error(error_msg)
            raise ValidationError(error_msg)
    
    def action_retry_creation(self):
        """Retry creating the knowledge base document"""
        if self.state == 'error':
            return self.create_elevenlabs_knowledge_base()
        else:
            raise ValidationError('Document is not in error state')
    

    
    def action_view_agents(self):
        """Action to view agents using this knowledge base document"""
        self.ensure_one()
        return {
            'name': f'Agents using "{self.name}"',
            'type': 'ir.actions.act_window',
            'res_model': 'connect.elevenlabs_agent',
            'view_mode': 'tree,form',
            'domain': [('knowledge_base', 'in', [self.id])],
            'context': {'default_knowledge_base': [(6, 0, [self.id])]}
        }
    
    def get_agents_using_document(self):
        """Get all agents that use this knowledge base document"""
        agents = self.env['connect.elevenlabs_agent'].search([
            ('knowledge_base', 'in', [self.id])
        ])
        return agents
    
    def add_to_agent(self, agent_id):
        """Add this knowledge document to an agent"""
        self.ensure_one()
        agent = self.env['connect.elevenlabs_agent'].browse(agent_id)
        if not agent.exists():
            raise ValidationError(f'Agent with ID {agent_id} not found')
        
        if self.id not in agent.knowledge_base.ids:
            agent.add_knowledge_documents(self.id)
            logger.info(f'Added knowledge document "{self.name}" to agent "{agent.name}"')
            return True
        
        logger.info(f'Knowledge document "{self.name}" already linked to agent "{agent.name}"')
        return False
    
    def remove_from_agent(self, agent_id):
        """Remove this knowledge document from an agent"""
        self.ensure_one()
        agent = self.env['connect.elevenlabs_agent'].browse(agent_id)
        if not agent.exists():
            raise ValidationError(f'Agent with ID {agent_id} not found')
        
        if self.id in agent.knowledge_base.ids:
            agent.remove_knowledge_documents(self.id)
            logger.info(f'Removed knowledge document "{self.name}" from agent "{agent.name}"')
            return True
        
        logger.info(f'Knowledge document "{self.name}" not linked to agent "{agent.name}"')
        return False
    
    def add_to_agents(self, agent_ids):
        """Add this knowledge document to multiple agents"""
        self.ensure_one()
        if not agent_ids:
            return False
        
        # Convert to list if single ID
        if isinstance(agent_ids, int):
            agent_ids = [agent_ids]
        
        success_count = 0
        for agent_id in agent_ids:
            if self.add_to_agent(agent_id):
                success_count += 1
        
        return success_count > 0
    
    def remove_from_agents(self, agent_ids):
        """Remove this knowledge document from multiple agents"""
        self.ensure_one()
        if not agent_ids:
            return False
        
        # Convert to list if single ID
        if isinstance(agent_ids, int):
            agent_ids = [agent_ids]
        
        success_count = 0
        for agent_id in agent_ids:
            if self.remove_from_agent(agent_id):
                success_count += 1
        
        return success_count > 0

