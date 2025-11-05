import React from 'react';
import { ConnectionStatus } from '../lib/api';

interface ConnectionBadgesProps {
  connections: ConnectionStatus;
  onGoogleConnect: () => void;
  onHubSpotConnect: () => void;
}

const ConnectionBadges: React.FC<ConnectionBadgesProps> = ({
  connections,
  onGoogleConnect,
  onHubSpotConnect,
}) => {
  // Google is connected if gmail is true (includes both Gmail & Calendar)
  const googleConnected = connections.gmail;
  
  return (
    <div className="space-y-4">
      <h3 className="text-lg font-semibold text-gray-900 mb-4">Connections</h3>
      
      {/* Gmail Connection */}
      <div className="flex items-center justify-between p-4 bg-white rounded-xl border border-gray-200 shadow-sm hover:shadow-md transition-shadow">
        <div className="flex items-center space-x-4">
          <div className={`w-3 h-3 rounded-full ${googleConnected ? 'bg-green-500' : 'bg-gray-300'}`} />
          <div>
            <p className="text-base font-medium text-gray-900">Gmail</p>
            <p className="text-sm text-gray-500">
              {googleConnected ? 'Connected' : 'Not connected'}
            </p>
          </div>
        </div>
        {!googleConnected && (
          <button
            onClick={onGoogleConnect}
            className="px-4 py-2 text-sm bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors font-medium"
          >
            Connect
          </button>
        )}
      </div>

      {/* Google Calendar Connection */}
      <div className="flex items-center justify-between p-4 bg-white rounded-xl border border-gray-200 shadow-sm hover:shadow-md transition-shadow">
        <div className="flex items-center space-x-4">
          <div className={`w-3 h-3 rounded-full ${googleConnected ? 'bg-green-500' : 'bg-gray-300'}`} />
          <div>
            <p className="text-base font-medium text-gray-900">Google Calendar</p>
            <p className="text-sm text-gray-500">
              {googleConnected ? 'Connected' : 'Not connected'}
            </p>
          </div>
        </div>
        {!googleConnected && (
          <button
            onClick={onGoogleConnect}
            className="px-4 py-2 text-sm bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors font-medium"
          >
            Connect
          </button>
        )}
      </div>

      {/* HubSpot Connection */}
      <div className="flex items-center justify-between p-4 bg-white rounded-xl border border-gray-200 shadow-sm hover:shadow-md transition-shadow">
        <div className="flex items-center space-x-4">
          <div className={`w-3 h-3 rounded-full ${connections.hubspot ? 'bg-green-500' : 'bg-gray-300'}`} />
          <div>
            <p className="text-base font-medium text-gray-900">HubSpot</p>
            <p className="text-sm text-gray-500">
              {connections.hubspot ? 'Connected' : 'Not connected'}
            </p>
          </div>
        </div>
        {!connections.hubspot && (
          <button
            onClick={onHubSpotConnect}
            className="px-4 py-2 text-sm bg-orange-600 text-white rounded-lg hover:bg-orange-700 transition-colors font-medium"
          >
            Connect
          </button>
        )}
      </div>
    </div>
  );
};

export default ConnectionBadges;
