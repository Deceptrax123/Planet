from pathlib import Path
import sys
import unittest
from unittest.mock import patch,Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
from discord_monitor import Publisher


class PublisherTests(unittest.TestCase):
    def test_research_task_changes_are_reported_without_prompts_or_commands(self):
        p=Publisher.__new__(Publisher)
        p.channels={'agent-activity':'activity','ji-eun-status':'status'}
        p.state={'initialized':True};p.send=Mock(return_value='message');p.save=Mock()
        data={'threads':[],'services':{},'reminders':{},'research':{'auth':'authenticated','tasks':[{'id':'r_abc','state':'working','engine':'codex','host':'petase-design','prompt':'SECRET_COMMAND'}]}}
        with patch('discord_monitor.snapshot',return_value=data):p.tick();p.tick()
        activity=[c for c in p.send.call_args_list if c.args[0]=='activity']
        self.assertEqual(len(activity),1)
        self.assertIn('Ji An / codex',activity[0].args[1]['content'])
        self.assertNotIn('SECRET_COMMAND',str(p.send.call_args_list))

    def test_short_completed_turn_is_reported_once_without_raw_commands(self):
        p=Publisher.__new__(Publisher)
        p.channels={'agent-activity':'activity','ji-eun-status':'status'}
        p.state={'initialized':True,'threads':{'session':'done|old'}}
        p.send=Mock(return_value='message');p.save=Mock()
        data={'threads':[{'id':'session','state':'done','role':'Ji Eun','model':'gpt-6-luna','parent_id':'','latest':{'at':'new','text':'mcp.add(secret)'},'title':'mcp.add(secret)'}], 'services':{'gateway':'active'},'reminders':{},'board':[],'deliveries':[],'schedules':[]}
        with patch('discord_monitor.snapshot',return_value=data):
            p.tick();p.tick()
        activity=[c for c in p.send.call_args_list if c.args[0]=='activity']
        self.assertEqual(len(activity),1)
        self.assertIn('finished',activity[0].args[1]['content'])
        self.assertNotIn('mcp.add',str(p.send.call_args_list))


if __name__=='__main__':unittest.main()
