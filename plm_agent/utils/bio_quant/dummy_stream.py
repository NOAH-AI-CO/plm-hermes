import asyncio
import io


async def dummy_stream(output:str, stream_status:dict = {}):
    stream_status_enabled = stream_status.get('enabled', False)
    if stream_status_enabled:
        stream_status['answer_content'] = io.StringIO()
        stream_status['reasoning_content'] = io.StringIO()
        stream_status['catalyst_data_obtained'] = True
        
    reasoning_output = "<think>\n" + "I'm thinking super hard!" + "</think>\n" 
    answer_output = output
    for c in reasoning_output:
        if stream_status_enabled:
            stream_status['reasoning_content'].write(c)
        yield c
        await asyncio.sleep(0)
    for c in answer_output:
        if stream_status_enabled:
            stream_status['answer_content'].write(c)
        yield c
        await asyncio.sleep(0)