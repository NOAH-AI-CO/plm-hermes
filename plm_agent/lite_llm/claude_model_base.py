# -*- coding: utf-8 -*-
from typing import Dict, Any


class ClaudeModelBase:
    
    def _get_valid_kwargs(
        self,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        r"""
        Get the valid kwargs from the kwargs.
        Args:
            kwargs(dict): The keyword arguments.
        Returns:
            Dict[str, Any]: The valid kwargs.
        """

        new_kwargs = {}

        # convert openai standard kwargs to vertex claude standard kwargs
        if 'reasoning' in kwargs:
            
            effort = kwargs.get('reasoning').get('effort', 'medium')
            if effort == 'low':
                budget_tokens = 1024 * 5
            elif effort == 'medium':
                budget_tokens = 1024 * 8
            elif effort == 'high':
                budget_tokens = 1024 * 10

            new_kwargs['thinking'] = {
                "type": "enabled",
                "budget_tokens": budget_tokens,
            }
        
        # max tokens
        max_tokens = 1024 * 16
        if new_kwargs.get('thinking'):
            max_tokens = new_kwargs.get('thinking', {}).get('budget_tokens', 0) + 1024 * 12
        new_kwargs['max_tokens'] = kwargs.get('max_output_tokens', max_tokens)

        valid_kwargs = [
            'temperature',
            'top_k',
            'top_p',
        ]
        filtered_kwargs = {k: v for k, v in kwargs.items() if k in valid_kwargs}
        # Merge new_kwargs (converted parameters) with filtered valid kwargs
        new_kwargs.update(filtered_kwargs)
        return new_kwargs