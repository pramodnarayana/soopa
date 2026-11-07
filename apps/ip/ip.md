Integration Platform
    We need to take best solutions from these open source. We don’t want to use the service  as it is. We want to use the code/inspiration and build our own product. We want to control the codebase and not depend on these .        1. N8N       2. Active pieces
       3.  AirbyteWe want to build Integration Platform for non-tech companies.  They don’t have to write  flows. We write the business flows.  We just provide  visualisation for customer support team to each and every  flow success and failure. Retry, etc
Note. We already build the below points . But that is in Typescript(/Users/apple/engineering/nexiom). We want it in Python.

1. Connection Life Cycle management. Customer support team should have a market place to choose the external app, SFTP, EDI, Kafa, API, etc and step the connection. Simple connection, Auth connection, Auth Connection. Once connection is done. We should be able to read, write, list all the object from the source system.  We want to design  one schema per connection.  Deleting, the connection  should not delete the schema, It should just  deactivate the schema. If the same connection is created  again the it should be liked to the same schema.  Recommend if schema per connection is true enterprise grade
2.  We will have     gateway Layer(inbound, and outbound), replication layer, and canonical normalisation  layer.   Canonical Layer is Domain Driven (Energy Sector will have MDN. All different MDM will converge to single schema in the normalisation layer).
   3. We will create Stitches(Business  Workflows) to transform data from one app to another.  We will have Global mapping table for source and destination. Which record from source system is linked to which record in the destination system.

  4. We will have AI agents that can answer our questions. (Like, what happened to the customer request for new meter installation. We have to get the data from source system and not from our system)
  5. Once the platform is ready, business flow writing should be easy and the platform should not be restarted for every business flow, and every new connection added.

  6. Business TraceId and correlation Id should be used (Not observability) to View the complete from inbound gateway layer to outbound gateway layer.  This is our Timeline view for customer support team



I want you to think like a true enterprise grade architect and provide solution.      1. For which component we need to use which open source inspiration(n8n, active pieces, air byte)
    2. Which we should write from scratch
    3.  Evaluate the current nexiom design. Check what design we need to borrow from there. Keep in mind we only wrote it. The connection pieces is taken from active pieces
    4. Soopa is our multi-app platform. We want everything  inside it.  Integration platform will set next to edi app. Would that be a good architecture.

Note: We are starting with Energy sector. `
