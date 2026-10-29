"""Expose exploration and routing without creating or opening a project."""
import unittest
from filmprod.action_schemas import action_help, tool_definitions, validate
from filmprod.exploration2100 import exploration_help
from filmprod.workflow_tools1110 import dispatch_arguments


class Help2100Tests(unittest.TestCase):
    def test_planning_help_uses_the_executable_command_contract(self):
        result = action_help('planning.record')
        self.assertTrue(result['read_only'])
        self.assertFalse(result['executed'])
        self.assertEqual(result['exploration'], exploration_help())
        payload = dict(op_id='TEST-P', expected_project_id='TEST', record_id='TEST-IDEA',
                       scope='TEST', base_version=1,
                       change=result['exploration']['example_select_change'])
        validate(payload, result['inputSchema'])
        validate({'expected_project_id': 'TEST', 'record_id': 'TEST-IDEA'}, action_help('planning.read')['inputSchema'])
        helper = next(t for t in tool_definitions({'type': 'string'}) if t['name'] == 'film_action_help')
        self.assertIn('planning.record', helper['inputSchema']['properties']['action']['enum'])

    def test_new_conversation_actions_are_exposed_and_strict(self):
        for action in ('conversation.route', 'conversation.route_accept', 'conversation.report'):
            result = action_help(action)
            self.assertTrue(result['read_only'])
            self.assertFalse(result['host_execution'])
            with self.assertRaises(ValueError):
                dispatch_arguments('film_conversations', {'action': action.split('.')[1], 'payload': {'expected_project_id': 'TEST'}})


if __name__ == '__main__':
    unittest.main()
