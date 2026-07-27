import json


def check_handle_tool_response(agent, response) -> str:
    """
    Use tools if response contains tool_calls.
    Args:
        agent (AgentPreset): The agent to use.
        response (str): The response content to use.
    Returns:
        str: The response content after using the tools.
    """
    
    if response.tool_calls:
        for tool_call in response.tool_calls:
            function_name = tool_call.function.name
            args = json.loads(tool_call.function.arguments)
            for tool in agent.tools:
                if tool.__name__ == function_name:
                    return tool().run(**args)
    else:
        return response.choices[0].message.content