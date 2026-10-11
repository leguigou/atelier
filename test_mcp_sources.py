import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('atelier_mcp_sources',Path(__file__).parent/'mcp'/'atelier_mcp.py')
mcp=importlib.util.module_from_spec(spec)
spec.loader.exec_module(mcp)


class McpSourceTests(unittest.TestCase):
    def test_add_sources_above_sixty_and_repeat_without_losing_memberships(self):
        ids=['source-'+str(i) for i in range(100)]
        book=dict(title='Livre',_revision='r1',source_ids=ids[:60],chapters=[])

        def api_call(method,path,body=None):
            if method=='PATCH':book.update(body)
            return book.copy()

        with patch.object(mcp.api,'call',side_effect=api_call),patch.object(mcp,'_index_sources',return_value=dict.fromkeys(ids,{})):
            result=mcp.ajouter_sources_livre(dict(book_id='book-main',source_ids=ids))
            self.assertEqual(result['matieres'],ids)
            self.assertIsNone(result['place_restante'])
            repeated=mcp.ajouter_sources_livre(dict(book_id='book-main',source_ids=ids))
            self.assertEqual(repeated['total'],100)
            listing=mcp.matieres_livre(dict(book_id='book-main'))
            self.assertIsNone(listing['maximum'])
            removed=mcp.retirer_sources_livre(dict(book_id='book-main',source_ids=[ids[-1]]))
            self.assertEqual(removed['matieres'],ids[:-1])
