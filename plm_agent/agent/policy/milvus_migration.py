import asyncio
from pymilvus import connections, Collection, utility, MilvusClient

def migrate_lightrag_data():
    # Connect to source Milvus instance (port 19530)
    connections.connect("source", host="localhost", port="19530", db_name="lightrag", keep_alive=True)
    
    # Connect to destination Milvus instance (port 19531)
    connections.connect("dest", host="localhost", port="19531", db_name="lightrag", keep_alive=True)

    # Get all collections from source instance
    source_collections = utility.list_collections(using="source")
    
    
    for collection_name in source_collections:
        try:
            print(f"Processing collection: {collection_name}")
            
            # Load source collection
            source_collection = Collection(collection_name, using="source")
            source_collection.flush()
            source_collection.load()
            print('1')
            
            # Get collection schema
            schema = source_collection.schema
            print('schema', schema)
            print('2')
            # Create destination collection with same schema
            prop = {"collection.ttl.seconds": 1800}
            dest_collection = Collection(collection_name, schema=schema, using="dest", timeout=1, properties=prop)
            print('3')
            
            # Query all data from source collection
            # Use query_iterator for large datasets
            iterator = source_collection.query_iterator(
                expr="",  # Empty expression to get all data
                output_fields=["*"],
                batch_size=1000
            )
            
            print('4')
            
            results = []
            while True:
                try:
                    batch = iterator.next()
                    if not batch:
                        break
                    dest_collection.upsert(batch)
                    dest_collection.flush()
                    
                    print(f"Inserted batch of {len(batch)} records for {collection_name}")
                except Exception as e:
                    print(f"Error during migration of {collection_name}: {e}")
                    break
            print('5')
            if results:
                # Insert data into destination collection
                dest_collection.insert(results)
                dest_collection.flush()
                print(f"Migrated {len(results)} records from {collection_name}")
            print('6')
            # Create index if exists on source
            try:
                # Get all indexes from source collection
                indexes = source_collection.indexes
                for index in indexes:
                    dest_collection.create_index(
                        field_name=index.field_name,
                        index_params=index.params,
                        index_name=index.index_name
                    )
                    print(f"Created index {index.index_name} for field {index.field_name}")
            except Exception as e:
                print(f"Note: Could not copy index for {collection_name}: {e}")
            print('7')
        except Exception as e:
            print(f"Failed to process collection {collection_name}: {e}")
    print("Migration completed")
    
def alter_varchar_field_length(collection_name="ah_relationships", field_name="tgt_id", new_max_length=768):
    """Alter the max length of a varchar field in a collection"""
    try:
        # Connect to destination Milvus instance using MilvusClient
        client = MilvusClient(
            uri="http://localhost:19530",
            token="root:Milvus",
            db_name="lightrag",
        )
        
        # Alter the field
        field_params = {"max_length": new_max_length}
        
        client.alter_collection_field(
            collection_name=collection_name, 
            field_name=field_name,
            field_params=field_params
        )
        
        print(f"Successfully altered {field_name} max_length to {new_max_length} in collection {collection_name}")
        
    except Exception as e:
        print(f"Failed to alter field {field_name} in collection {collection_name}: {e}")

if __name__ == "__main__":
    # migrate_lightrag_data()
    alter_varchar_field_length()